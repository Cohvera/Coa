import copy
import io
import os
from pathlib import Path
import tempfile
import unittest
import openpyxl
from fastapi.testclient import TestClient

_tmp = tempfile.TemporaryDirectory()
os.environ['QHOME_DATA_DIR'] = _tmp.name
os.environ['QHOME_ADMIN_PASSWORD'] = 'test-admin-only'
os.environ['QHOME_USER_PASSWORD'] = 'test-user-only'
from app import main
from app.importer import parse, inspect, number
from app.pricing import calculate, match


def workbook_bytes(formula=False):
    w = openpyxl.Workbook()
    s = w.active
    s.title = 'Elektriciteit'
    s.append(['Omschrijving', 'Aantal', 'Eenheid'])
    s.append(['Enkel stopcontact', '=1+2' if formula else 3, 'St.'])
    out = io.BytesIO()
    w.save(out)
    return out.getvalue()


MAPPING = dict(description='A', quantity='B', unit='C', code='', context='', start=2)


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.line = parse(workbook_bytes(), 'Elektriciteit', MAPPING)['lines'][0]
        self.item = dict(id='price1', name='Enkel stopcontact', unit='st', price='12.35', active=True, aliases=[])
        match([self.line], [self.item])

    def test_rounding_discount_fixed_vat(self):
        c = calculate([self.line], dict(discount='10', fixed='5', vat='21'), [self.item])
        self.assertTrue(c['ready'])
        self.assertEqual((c['subtotal'], c['discount_amount'], c['net'], c['gross']), ('37.05', '3.71', '38.34', '46.39'))

    def test_unknown_zero_and_excluded(self):
        self.item['price'] = None
        self.assertFalse(calculate([self.line], {}, [self.item])['ready'])
        self.item['price'] = '0'
        self.assertTrue(calculate([self.line], {}, [self.item])['ready'])
        self.line['quantity'] = None
        self.assertFalse(calculate([self.line], {}, [self.item])['ready'])
        self.line.update(excluded=True, reason='Niet in opdracht')
        self.assertFalse(calculate([self.line], {}, [self.item])['ready'], 'An empty offer must not finalize')

    def test_units_ambiguous_matches_and_invalid_numbers(self):
        self.item['unit'] = 'm'
        self.assertFalse(calculate([self.line], {}, [self.item])['ready'])
        self.item['unit'] = 'st'
        match([self.line], [self.item, dict(self.item, id='duplicate')])
        self.assertIsNone(self.line['catalog_id'])
        for value in ('NaN', 'Infinity', '-1', True, '1e100'):
            with self.assertRaises(ValueError): number(value)
        self.assertEqual(number('1.234,5'), '1234.5')

    def test_formula_without_cache(self):
        line = parse(workbook_bytes(True), 'Elektriciteit', MAPPING)['lines'][0]
        self.assertIsNone(line['quantity'])
        self.assertIn('Formule', line['issue'])

    def test_context_and_group_reset(self):
        w = openpyxl.Workbook(); s = w.active
        s.append(['0710.06','KEURINGEN',None,None])
        s.append([None,'Opmaak keuringen',None,None])
        s.append([None,None,None,'Gemene delen',1,'st'])
        s.append([None,'Opmaak AS-Built dossier',None,None])
        s.append([None,None,None,'Gemene delen',1,'st'])
        out=io.BytesIO();w.save(out)
        rows=parse(out.getvalue(),s.title,dict(description='D',quantity='E',unit='F',code='A',context='B',start=1))['lines']
        self.assertEqual([r['match_text'] for r in rows], ['Opmaak keuringen / Gemene delen','Opmaak AS-Built dossier / Gemene delen'])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(main.app)
        self.assertEqual(self.client.post('/api/login',json={'password':'test-admin-only'}).status_code,200)

    def draft(self):
        upload=self.client.post('/api/uploads',files={'file':('sample.xlsx',workbook_bytes())}).json()
        response=self.client.post('/api/drafts',json={'upload_id':upload['id'],'sheet':'Elektriciteit','mapping':MAPPING})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_auth_and_admin_boundary(self):
        other=TestClient(main.app)
        self.assertEqual(other.get('/api/catalog').status_code,401)
        other.post('/api/login',json={'password':'test-user-only'})
        self.assertEqual(other.post('/api/catalog',json={'name':'Denied','unit':'st','price':1}).status_code,403)
        self.assertEqual(other.post('/api/drafts/x/catalog').status_code,403)
        self.assertEqual(other.post('/api/logout',headers={'Origin':'https://evil.example'}).status_code,403)
        other.post('/api/logout')
        self.assertEqual(other.get('/api/catalog').status_code,401)

    def test_end_to_end_immutable_offer_and_escaping(self):
        d=self.draft(); line=d['lines'][0]
        item=next(c for c in self.client.get('/api/catalog').json() if c['id']==line['catalog_id'])
        item['price']='12.35';self.client.post('/api/catalog',json=item)
        d['settings'].update(project='<script>test</script>',customer='Testklant',discount='10',fixed='5',vat='21')
        d['reviewed']=True
        response=self.client.put('/api/drafts/'+d['id'],json=d)
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.post('/api/drafts/'+d['id']+'/offers')
        self.assertEqual(response.status_code,200,response.text)
        offer=response.json();self.assertEqual(offer['calculation']['gross'],'46.39')
        item['price']='999';self.client.post('/api/catalog',json=item)
        printable=self.client.get('/api/offers/'+offer['id']+'/print').text
        self.assertIn('&lt;script&gt;',printable);self.assertNotIn('<script>test',printable)
        csv=self.client.get('/api/offers/'+offer['id']+'/csv').text
        self.assertIn('12,35',csv);self.assertNotIn('999',csv)

    def test_incomplete_and_tampered_draft(self):
        d=self.draft()
        self.assertEqual(self.client.post('/api/drafts/'+d['id']+'/offers').status_code,400)
        tampered=copy.deepcopy(d);tampered['lines']=[]
        self.assertEqual(self.client.put('/api/drafts/'+d['id'],json=tampered).status_code,400)
        d['lines'][0].update(excluded=True,reason=None)
        self.client.put('/api/drafts/'+d['id'],json=d)
        c=self.client.get('/api/drafts/'+d['id']+'/calculation').json()
        self.assertIn('reden',c['lines'][0]['pricing_error'])

    def test_invalid_upload_and_csv_injection(self):
        self.assertEqual(self.client.post('/api/uploads',files={'file':('test.xlsx',b'not a zip')}).status_code,400)
        self.assertEqual(self.client.post('/api/uploads',files={'file':('test.xls',b'x')}).status_code,400)
        self.assertEqual(main.safe_csv('=HYPERLINK("x")'),'\'=HYPERLINK("x")')

    @unittest.skipUnless(os.environ.get('QHOME_SAMPLE_XLSX'),'Set QHOME_SAMPLE_XLSX for customer sample integration')
    def test_optional_local_workbook(self):
        data=Path(os.environ['QHOME_SAMPLE_XLSX']).read_bytes()
        sheets=inspect(data)
        sheet=next(s for s in sheets if 'ELEKTR' in s['name'].upper())
        rows=parse(data,sheet['name'],sheet['mapping'])['lines']
        self.assertTrue(rows)
        self.assertEqual(len(rows),len({r['source_row'] for r in rows}))
        for row in rows:
            self.assertEqual(row['quantity'],row['source_quantity'])
            self.assertEqual(row['sheet'],sheet['name'])
            if row['quantity'] is None:
                self.assertTrue(row['issue'])


if __name__=='__main__': unittest.main()
