const $ = (s) => document.querySelector(s);
const state = {role: null, upload: null, draft: null, catalog: [], calculation: null, dirty: false};
const eur = (n) => new Intl.NumberFormat('nl-BE', {style:'currency', currency:'EUR'}).format(Number(n));
const escape = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notify(message, error = false) { $('#notice').textContent = message; $('#notice').className = error ? 'error' : ''; $('#notice').hidden = false; }
async function api(path, options = {}) {
  const response = await fetch('/api' + path, options);
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') { state.role = null; showPage('login'); }
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Controleer de invoer.');
  }
  return data;
}
const json = (method, body) => ({method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
function run(action) { return async (event) => {event?.preventDefault(); const button = event?.submitter || (event?.currentTarget?.tagName === 'BUTTON' ? event.currentTarget : null); if(button) button.disabled = true; try { await action(event); } catch(error) { notify(error.message, true); } finally { if(button) button.disabled = false; }}; }
function showPage(page) { if (!state.role) page = 'login'; document.querySelectorAll('.page').forEach(p => p.hidden = p.id !== page + '-page'); document.querySelectorAll('[data-page]').forEach(b => b.classList.toggle('selected', b.dataset.page === page)); $('#admin-nav').hidden = state.role !== 'admin'; $('#logout').hidden = !state.role; $('#role-label').textContent = state.role === 'admin' ? 'Beheerder · Q-Home' : state.role ? 'Calculator · Q-Home' : 'Beveiligde werkruimte'; }
async function navigate(page) {
  if(state.dirty && state.draft) await saveDraft(false);
  if(page === 'admin') { state.catalog = await api('/catalog'); renderCatalog(); }
  if(page === 'offers') await renderOffers();
  if(page === 'import') await renderDrafts();
  if(page === 'quote' && state.draft) { state.catalog = await api('/catalog'); await refreshCalculation(); renderDraft(); }
  showPage(page);
}
document.querySelectorAll('[data-page]').forEach(b => b.addEventListener('click', run(() => navigate(b.dataset.page))));
$('#login-form').addEventListener('submit', run(async () => {const user = await api('/login', json('POST', {password:$('#password').value})); $('#password').value = ''; state.role = user.role; state.catalog = await api('/catalog'); $('#notice').hidden = true; await navigate('import');}));
$('#logout').addEventListener('click', run(async () => { if(state.dirty) await saveDraft(false); await api('/logout', {method:'POST'}); state.role = null; state.draft = null; showPage('login'); }));
$('#upload-form').addEventListener('submit', run(async () => {const form = new FormData(); const file = $('#file').files[0]; if (!file) throw Error('Kies eerst een bestand.'); form.append('file', file); state.upload = await api('/uploads', {method:'POST', body:form}); $('#sheet').innerHTML = state.upload.sheets.map(s => `<option>${escape(s.name)}</option>`).join(''); const preferred = state.upload.sheets.find(s => /elektr/i.test(s.name)); if(preferred) $('#sheet').value = preferred.name; $('#mapping-panel').hidden = false; renderMapping(); notify('Bestand ingelezen. Controleer werkblad, kolommen en eerste detailrij.'); }));
function renderMapping() {const sheet = state.upload.sheets.find(s => s.name === $('#sheet').value); Object.entries(sheet.mapping).forEach(([k,v]) => $('#map-' + k).value = v); $('#source-preview').innerHTML = '<table><thead><tr><th>Rij</th>' + (sheet.sample[0] || []).map((_,i) => `<th>${String.fromCharCode(65 + Math.floor(i/26)-1).replace('@','')}${String.fromCharCode(65+i%26)}</th>`).join('') + '</tr></thead><tbody>' + sheet.sample.map((r,i) => `<tr><td>${i+1}</td>${r.map(v => `<td>${escape(v)}</td>`).join('')}</tr>`).join('') + '</tbody></table>'; }
$('#sheet').addEventListener('change', renderMapping);
$('#mapping-form').addEventListener('submit', run(async () => {const mapping = {}; ['description','quantity','unit','code','context','start'].forEach(k => mapping[k] = $('#map-'+k).value); state.draft = await api('/drafts', json('POST', {upload_id:state.upload.id, sheet:$('#sheet').value, mapping})); state.catalog = await api('/catalog'); state.dirty = false; await refreshCalculation(); renderDraft(); showPage('quote'); notify(`${state.draft.lines.length} bronregels ingelezen. Controleer de aandachtspunten.`); }));
async function renderDrafts() {const drafts = await api('/drafts'); $('#draft-list').innerHTML = drafts.length ? drafts.map(d => `<div class="list-row"><span>${escape(d.project)}</span><button class="secondary" data-draft="${escape(d.id)}">Verder werken →</button></div>`).join('') : 'Nog geen calculaties.'; $('#draft-list').querySelectorAll('[data-draft]').forEach(b => b.addEventListener('click', run(async () => {state.draft = await api('/drafts/'+b.dataset.draft); state.dirty = false; await navigate('quote');}))); }
async function refreshCalculation() {state.calculation = await api(`/drafts/${state.draft.id}/calculation`);}
function renderDraft() {
  const d = state.draft; $('#quote-body').hidden = false; $('#quote-title').textContent = d.settings.project || 'Je project, doorgerekend.'; $('#quote-source').textContent = `${d.filename} · ${d.sheet}`;
  document.querySelectorAll('[data-setting]').forEach(i => i.value = d.settings[i.dataset.setting]);
  $('#reviewed').checked = d.reviewed; $('#seed-catalog').hidden = state.role !== 'admin';
  $('#source-notes').innerHTML = d.notes.map(n => `<li>Rij ${n.row}: ${escape(n.text)}</li>`).join('') || '<li>Geen afzonderlijke notities herkend. Controleer de oorspronkelijke meetstaat.</li>';
  renderMetrics(); renderLines();
}
function renderMetrics() {const c = state.calculation; $('#metric-lines').textContent = state.draft.lines.length; $('#metric-errors').textContent = c.errors.length; $('#metric-net').textContent = eur(c.net); $('#net-label').textContent = c.ready ? 'TOTAAL EXCL. BTW' : 'BEKEND DEELBEDRAG EXCL. BTW'; $('#final-status').textContent = c.ready ? `Incl. btw: ${eur(c.gross)}. Bevestig je controle en bewaar het voorstel.` : `${c.errors.length} aandachtspunten. Het bekende deelbedrag is geen volledige offerte.`; }
function markDirty() {state.dirty = true; state.draft.reviewed = false; $('#reviewed').checked = false; $('#net-label').textContent = 'VORIGE BEREKENING · OPNIEUW OPSLAAN'; $('#final-status').textContent = 'Je hebt wijzigingen. Sla op en bereken opnieuw.';}
document.querySelectorAll('[data-setting]').forEach(i => i.addEventListener('input', () => {if(state.draft) {state.draft.settings[i.dataset.setting] = i.value; markDirty();}}));
function renderLines() {
  const search = $('#line-search').value.toLowerCase(), onlyErrors = $('#only-errors').checked;
  const priced = new Map(state.calculation.lines.map(l => [l.id,l]));
  const lines = state.draft.lines.filter(l => (!search || [l.description,l.context,l.group,l.section].join(' ').toLowerCase().includes(search)) && (!onlyErrors || priced.get(l.id)?.pricing_error));
  $('#line-count').textContent = `${lines.length} van ${state.draft.lines.length} regels zichtbaar`;
  $('#line-rows').innerHTML = lines.map(l => {const p = priced.get(l.id); const opts = state.catalog.filter(c => c.active || c.id === l.catalog_id).map(c => `<option value="${escape(c.id)}" ${c.id===l.catalog_id?'selected':''}>${escape(c.name)} · ${escape(c.unit)}${!c.active?' (inactief)':''}</option>`).join(''); return `<tr data-line="${l.id}" class="${l.excluded?'excluded':p?.pricing_error?'problem':''}"><td>Rij ${l.source_row}<small>${escape(l.section)}</small><small>${escape(l.group)}</small><small>${escape(l.context)}</small></td><td>${escape(l.description)}<small class="warning">${escape(p?.pricing_error)}</small>${l.issue?`<small>Bron: ${escape(l.issue)}</small>`:''}</td><td><input data-field="quantity" aria-label="Aantal rij ${l.id}" type="number" min="0" step="any" value="${escape(l.quantity)}"><input data-field="unit" aria-label="Eenheid rij ${l.id}" value="${escape(l.unit)}"><small>Bron: ${escape(l.source_quantity ?? 'ontbreekt')} ${escape(l.source_unit)}</small></td><td><select data-field="catalog_id" aria-label="Prijspost rij ${l.id}"><option value="">Kies standaardpost…</option>${opts}</select></td><td>${p?.price!=null?eur(p.price):'—'}<small>${p?.total!=null?eur(p.total):'—'}</small></td><td><label class="check"><input data-field="included" type="checkbox" ${!l.excluded?'checked':''}> Ja</label><input data-field="reason" aria-label="Reden uitsluiting rij ${l.id}" placeholder="Reden uitsluiting" value="${escape(l.reason)}" ${!l.excluded?'hidden':''}></td></tr>`;}).join('');
  $('#line-rows').querySelectorAll('[data-field]').forEach(input => input.addEventListener('input', () => {const tr = input.closest('tr'); const line = state.draft.lines.find(l=>l.id===Number(tr.dataset.line)); const field=input.dataset.field; if(field==='included') {line.excluded=!input.checked;tr.querySelector('[data-field=reason]').hidden=input.checked;tr.classList.toggle('excluded',line.excluded);} else line[field] = input.value || null; markDirty();}));
}
$('#line-search').addEventListener('input', renderLines); $('#only-errors').addEventListener('change', renderLines);
async function saveDraft(message = true) {if(!state.draft) throw Error('Importeer eerst een meetstaat.'); state.draft = await api(`/drafts/${state.draft.id}`, json('PUT', state.draft)); state.dirty = false; await refreshCalculation(); renderDraft(); if(message) notify('Calculatie opgeslagen en opnieuw berekend.');}
$('#save').addEventListener('click', run(() => saveDraft()));
$('#reviewed').addEventListener('change', () => {state.draft.reviewed = $('#reviewed').checked; state.dirty = true;});
$('#seed-catalog').addEventListener('click', run(async () => {await saveDraft(false); const result = await api(`/drafts/${state.draft.id}/catalog`, {method:'POST'}); state.draft = result.draft; await navigate('admin'); notify(`${result.created} standaardposten toegevoegd met een lege prijs. Vul de all-in prijzen in; ga daarna terug naar Calculatie.`);}));
$('#finalize').addEventListener('click', run(async () => {await saveDraft(false); const offer = await api(`/drafts/${state.draft.id}/offers`, {method:'POST'}); await navigate('offers'); notify(`Prijsvoorstel ${offer.number} bewaard. De gebruikte prijzen liggen nu vast.`);}));
function renderCatalog() {
  const search = $('#catalog-search').value.toLowerCase();
  $('#catalog-rows').innerHTML = state.catalog.filter(c => c.name.toLowerCase().includes(search)).map(c => `<tr data-item="${escape(c.id)}"><td><input data-key="name" aria-label="Omschrijving" value="${escape(c.name)}"></td><td><input data-key="unit" aria-label="Eenheid" value="${escape(c.unit)}"></td><td><input data-key="price" aria-label="All-in prijs voor ${escape(c.name)}" type="number" min="0" step="0.01" value="${escape(c.price)}" placeholder="Ontbreekt"></td><td><textarea data-key="aliases" aria-label="Herkenningsnamen">${escape(c.aliases.join('\n'))}</textarea></td><td><input data-key="active" aria-label="Actief" type="checkbox" ${c.active?'checked':''}></td><td><button class="secondary" data-save-item>Opslaan</button></td></tr>`).join('');
  $('#catalog-rows').querySelectorAll('[data-save-item]').forEach(b => b.addEventListener('click', run(async () => {const tr=b.closest('tr'); const item={id:tr.dataset.item}; tr.querySelectorAll('[data-key]').forEach(i => item[i.dataset.key] = i.dataset.key==='active'?i.checked:i.dataset.key==='aliases'?i.value.split('\n'):i.value); const updated=await api('/catalog',json('POST',item)); state.catalog=state.catalog.map(c=>c.id===updated.id?updated:c); b.textContent='Opgeslagen'; notify(`Standaardprijs opgeslagen: ${updated.name}. Bestaande prijsvoorstellen blijven behouden.`);}))); }
$('#catalog-search').addEventListener('input', renderCatalog);
$('#new-item-form').addEventListener('submit', run(async () => {await api('/catalog',json('POST',{name:$('#new-name').value,unit:$('#new-unit').value,price:$('#new-price').value})); $('#new-name').value='';$('#new-price').value='';state.catalog=await api('/catalog');renderCatalog();notify('Standaardpost toegevoegd.');}));
async function renderOffers() {const offers=await api('/offers'); $('#offer-list').innerHTML=offers.length?offers.map(o=>`<div class="list-row"><div><b>${escape(o.project)}</b><small>${escape(o.number)} · ${eur(o.net)} excl. btw</small></div><div><a href="/api/offers/${escape(o.id)}/print" target="_blank" rel="noopener">Bekijken / PDF ↗</a><a href="/api/offers/${escape(o.id)}/csv">Download CSV ↓</a></div></div>`).join(''):'Nog geen prijsvoorstellen. Bewaar eerst een gecontroleerde calculatie.';}
window.addEventListener('beforeunload', event => {if(state.dirty) {event.preventDefault();event.returnValue='';}});
(async () => {try {state.role=(await api('/session')).role;state.catalog=await api('/catalog');await navigate('import');} catch {showPage('login');}})();
