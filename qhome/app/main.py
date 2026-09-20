import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from contextlib import contextmanager
from uuid import uuid4
from urllib.parse import urlparse
from fastapi import FastAPI, Request, Response, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .importer import inspect, parse, number, unit, normalize, MAX_BYTES
from .pricing import calculate, match, money

BASE = Path(__file__).parent
DATA = Path(os.environ.get("QHOME_DATA_DIR", BASE.parent / "data"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "qhome.sqlite3"


@contextmanager
def connection():
    db = sqlite3.connect(DB, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS catalog(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY, filename TEXT, body BLOB, created REAL);
        CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS offers(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, role TEXT, expires REAL);
        CREATE TABLE IF NOT EXISTS login_attempts(ip TEXT, created REAL);
        """)
        if not db.execute("SELECT 1 FROM catalog LIMIT 1").fetchone():
            for name in ("Enkel stopcontact", "Dubbel stopcontact", "Hermetisch stopcontact", "Stopcontact - UTP",
                         "Stopcontact - Distributie TV", "Stopcontact - Oven", "Stopcontact - Kookplaat",
                         "Stopcontact - Wasmachine en droogkast", "Lichtpunt - Enkelvoudige richting",
                         "Lichtpunt - Tweevoudige richting", "Lichtpunt - Drievoudige richting", "Bewegingssensor",
                         "Zekeringkast", "Optische rookmelders", "Opmaak keuringen / Gemene delen",
                         "Opmaak keuringen / Privatieven", "Opmaak AS-Built dossier / Gemene delen",
                         "Opmaak AS-Built dossier / Privatieven"):
                item = {"id": str(uuid4()), "name": name, "unit": "st", "price": None, "aliases": [], "active": True}
                db.execute("INSERT INTO catalog VALUES (?,?)", (item["id"], json.dumps(item)))


initialize()
app = FastAPI(title="Q-Home projectoffertes", docs_url=None, redoc_url=None)


@app.middleware("http")
async def secure_headers(request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and urlparse(origin).netloc != request.headers.get("host"):
        return JSONResponse({"detail": "Verzoek vanaf een andere website geweigerd."}, 403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({"detail": str(exc)}, 400)


def session(request: Request):
    token = hashlib.sha256(request.cookies.get("qhome_session", "").encode()).hexdigest()
    with connection() as db:
        row = db.execute("SELECT role FROM sessions WHERE token=? AND expires>?", (token, time.time())).fetchone()
    if not row:
        raise HTTPException(401, "Meld je aan om verder te gaan.")
    return row["role"]


def admin(role=Depends(session)):
    if role != "admin":
        raise HTTPException(403, "Alleen een beheerder kan standaardprijzen aanpassen.")
    return role


def get_json(table, key):
    # Table names are internal constants, never request values.
    with connection() as db:
        row = db.execute(f"SELECT body FROM {table} WHERE id=?", (key,)).fetchone()
    if not row:
        raise HTTPException(404, "Niet gevonden.")
    return json.loads(row["body"])


def put_json(table, key, body):
    with connection() as db:
        db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)", (key, json.dumps(body)))


def catalog():
    with connection() as db:
        return sorted([json.loads(r["body"]) for r in db.execute("SELECT body FROM catalog")], key=lambda c: c["name"].casefold())


@app.get("/api/health")
def health():
    return {"ok": True, "service": "qhome-offertes"}


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    password = str(body.get("password", ""))
    admin_password, user_password = os.environ.get("QHOME_ADMIN_PASSWORD", ""), os.environ.get("QHOME_USER_PASSWORD", "")
    if not admin_password:
        raise HTTPException(503, "Stel QHOME_ADMIN_PASSWORD in op de server.")
    ip = request.client.host if request.client else "unknown"
    with connection() as db:
        db.execute("DELETE FROM login_attempts WHERE created<?", (time.time() - 300,))
        if db.execute("SELECT count(*) FROM login_attempts WHERE ip=?", (ip,)).fetchone()[0] >= 10:
            raise HTTPException(429, "Te veel pogingen. Probeer over vijf minuten opnieuw.")
        db.execute("INSERT INTO login_attempts VALUES (?,?)", (ip, time.time()))
    role = "admin" if secrets.compare_digest(password.encode(), admin_password.encode()) else "user" if user_password and secrets.compare_digest(password.encode(), user_password.encode()) else None
    if not role:
        raise HTTPException(401, "Onjuist wachtwoord.")
    token = secrets.token_urlsafe(32)
    with connection() as db:
        db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        db.execute("INSERT INTO sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), role, time.time() + 43200))
        db.execute("DELETE FROM login_attempts WHERE ip=?", (ip,))
    response = JSONResponse({"role": role})
    response.set_cookie("qhome_session", token, httponly=True, samesite="strict", max_age=43200,
                        secure=os.environ.get("QHOME_SECURE_COOKIE", "0") == "1")
    return response


@app.get("/api/session")
def current_session(role=Depends(session)):
    return {"role": role}


@app.post("/api/logout")
def logout(request: Request):
    with connection() as db:
        db.execute("DELETE FROM sessions WHERE token=?", (hashlib.sha256(request.cookies.get("qhome_session", "").encode()).hexdigest(),))
    response = JSONResponse({"ok": True})
    response.delete_cookie("qhome_session")
    return response


@app.get("/api/catalog")
def list_catalog(role=Depends(session)):
    return catalog()


@app.post("/api/catalog")
async def save_catalog(request: Request, role=Depends(admin)):
    body = await request.json()
    name, item_unit = str(body.get("name", "")).strip(), unit(body.get("unit"))
    if not name or len(name) > 300 or not item_unit or len(item_unit) > 20:
        raise ValueError("Naam en eenheid zijn verplicht (maximaal 300 en 20 tekens).")
    price = number(body.get("price"))
    aliases = body.get("aliases", [])
    if not isinstance(aliases, list) or len(aliases) > 100 or any(not isinstance(a, str) or len(a) > 300 for a in aliases):
        raise ValueError("Ongeldige herkenningsnamen.")
    key = body.get("id") or str(uuid4())
    if body.get("id"):
        get_json("catalog", key)
    item = {"id": key, "name": name, "unit": item_unit, "price": str(money(price)) if price is not None else None,
            "aliases": [a.strip() for a in aliases if a.strip()], "active": bool(body.get("active", True))}
    if any(c["id"] != key and normalize(c["name"]) == normalize(name) and c["unit"] == item_unit for c in catalog()):
        raise ValueError("Deze prijspost en eenheid bestaan al.")
    put_json("catalog", key, item)
    return item


@app.post("/api/uploads")
async def upload(file: UploadFile = File(...), role=Depends(session)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise ValueError("Gebruik een .xlsx-bestand.")
    data = await file.read(MAX_BYTES + 1)
    try:
        sheets = inspect(data)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Het Excel-bestand kon niet worden gelezen.") from exc
    key = str(uuid4())
    with connection() as db:
        db.execute("DELETE FROM uploads WHERE created<?", (time.time() - 86400,))
        db.execute("INSERT INTO uploads VALUES (?,?,?,?)", (key, Path(file.filename).name, data, time.time()))
    return {"id": key, "filename": Path(file.filename).name, "sheets": sheets}


@app.post("/api/drafts")
async def create_draft(request: Request, role=Depends(session)):
    body = await request.json()
    with connection() as db:
        source = db.execute("SELECT * FROM uploads WHERE id=?", (body.get("upload_id"),)).fetchone()
    if not source:
        raise ValueError("Upload verlopen. Laad het bestand opnieuw op.")
    parsed = parse(source["body"], body.get("sheet"), body.get("mapping", {}))
    key = str(uuid4())
    draft = {"id": key, "filename": source["filename"], "sheet": body["sheet"], "mapping": body["mapping"],
             "lines": match(parsed["lines"], catalog()), "notes": parsed["notes"], "reviewed": False,
             "settings": {"project": Path(source["filename"]).stem, "customer": "", "discount": "0", "fixed": "0", "vat": "21", "conditions": "", "validity": "30 dagen"}}
    put_json("drafts", key, draft)
    return draft


@app.get("/api/drafts")
def list_drafts(role=Depends(session)):
    with connection() as db:
        return [{"id": d["id"], "project": d["settings"]["project"]} for r in db.execute("SELECT body FROM drafts ORDER BY rowid DESC") for d in [json.loads(r["body"])]]


@app.get("/api/drafts/{key}")
def read_draft(key: str, role=Depends(session)):
    return get_json("drafts", key)


@app.put("/api/drafts/{key}")
async def update_draft(key: str, request: Request, role=Depends(session)):
    draft = get_json("drafts", key)
    body = await request.json()
    incoming = body.get("lines", [])
    if not isinstance(incoming, list) or len(incoming) != len(draft["lines"]) or {r.get("id") for r in incoming} != {r["id"] for r in draft["lines"]}:
        raise ValueError("De bronregels moeten behouden blijven.")
    edits = {r["id"]: r for r in incoming}
    for line in draft["lines"]:
        edit = edits[line["id"]]
        line["quantity"] = number(edit.get("quantity"))
        line["unit"] = unit(edit.get("unit"))
        line["catalog_id"] = edit.get("catalog_id")
        line["excluded"] = edit.get("excluded") is True
        line["reason"] = str(edit.get("reason") or "")[:1000]
    settings = body.get("settings", {})
    for field in draft["settings"]:
        draft["settings"][field] = str(settings.get(field, draft["settings"][field]))[:4000]
    draft["reviewed"] = body.get("reviewed") is True
    calculate(draft["lines"], draft["settings"], catalog())
    put_json("drafts", key, draft)
    return draft


@app.post("/api/drafts/{key}/catalog")
def add_missing_catalog(key: str, role=Depends(admin)):
    draft, items = get_json("drafts", key), catalog()
    created = 0
    for line in draft["lines"]:
        if line["catalog_id"] or not line["unit"] or any(normalize(c["name"]) == normalize(line["match_text"]) and c["unit"] == line["unit"] for c in items):
            continue
        item = {"id": str(uuid4()), "name": line["match_text"], "unit": line["unit"], "price": None, "aliases": [], "active": True}
        put_json("catalog", item["id"], item)
        items.append(item)
        created += 1
    # Preserve explicit user mappings; only fill unmapped rows.
    for line in draft["lines"]:
        if not line["catalog_id"]:
            match([line], items)
    draft["reviewed"] = False
    put_json("drafts", key, draft)
    return {"created": created, "draft": draft}


@app.get("/api/drafts/{key}/calculation")
def preview(key: str, role=Depends(session)):
    draft = get_json("drafts", key)
    return calculate(draft["lines"], draft["settings"], catalog())


@app.post("/api/drafts/{key}/offers")
def finalize(key: str, role=Depends(session)):
    draft = get_json("drafts", key)
    calculation = calculate(draft["lines"], draft["settings"], catalog())
    if not draft["reviewed"] or not calculation["ready"]:
        raise ValueError("Controleer alle regels, prijzen en bronvoorwaarden en bevestig de controle.")
    if not draft["settings"]["project"].strip() or not draft["settings"]["customer"].strip():
        raise ValueError("Vul projectnaam en klant in.")
    offer_id = str(uuid4())
    offer = {"id": offer_id, "number": "QH-" + time.strftime("%Y%m%d") + "-" + offer_id[:8].upper(),
             "created": time.strftime("%Y-%m-%d"), "settings": draft["settings"], "filename": draft["filename"],
             "sheet": draft["sheet"], "notes": draft["notes"], "calculation": calculation}
    put_json("offers", offer_id, offer)
    return offer


@app.get("/api/offers")
def list_offers(role=Depends(session)):
    with connection() as db:
        return [{"id": o["id"], "number": o["number"], "project": o["settings"]["project"], "net": o["calculation"]["net"]}
                for r in db.execute("SELECT body FROM offers ORDER BY rowid DESC") for o in [json.loads(r["body"])]]


def safe_csv(value):
    text = str(value or "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


@app.get("/api/offers/{key}/csv")
def export_csv(key: str, role=Depends(session)):
    offer = get_json("offers", key)
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["Offerte", offer["number"], safe_csv(offer["settings"]["project"])])
    writer.writerow(["Hoofdstuk", "Groep", "Ruimte/context", "Omschrijving", "Aantal", "Eenheid", "Eenheidsprijs", "Totaal", "Status", "Reden", "Bronrij"])
    for line in offer["calculation"]["lines"]:
        writer.writerow([safe_csv(line[k]) for k in ("section", "group", "context", "description")] +
                        [safe_csv(str(line.get(k) or "").replace(".", ",")) for k in ("quantity", "unit", "price", "total")] +
                        ["Uitgesloten" if line["excluded"] else "Inbegrepen", safe_csv(line["reason"]), line["source_row"]])
    for label, field in (("Subtotaal", "subtotal"), ("Korting", "discount_amount"), ("Vaste projectkosten", "fixed"), ("Excl. btw", "net"), ("Btw", "vat_amount"), ("Incl. btw", "gross")):
        writer.writerow([label, offer["calculation"][field].replace(".", ",")])
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{offer["number"]}.csv"'})


@app.get("/api/offers/{key}/print", response_class=HTMLResponse)
def print_offer(key: str, role=Depends(session)):
    o = get_json("offers", key)
    esc = lambda s: html.escape(str(s or ""))
    euros = lambda s: "€ " + f"{float(s):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    rows = "".join(f'<tr><td>{esc(l["section"])}<br>{esc(l["group"])} / {esc(l["context"])}</td><td>{esc(l["description"])}</td><td>{esc(l["quantity"])}</td><td>{esc(l["unit"])}</td><td>{euros(l["price"])}</td><td>{euros(l["total"])}</td></tr>' for l in o["calculation"]["lines"] if not l["excluded"])
    exclusions = "".join(f'<li>{esc(l["description"])} — {esc(l["reason"])}</li>' for l in o["calculation"]["lines"] if l["excluded"])
    totals = "".join(f'<p>{label}: <strong>{euros(o["calculation"][field])}</strong></p>' for label, field in (("Subtotaal", "subtotal"), ("Korting", "discount_amount"), ("Vaste projectkosten", "fixed"), ("Totaal excl. btw", "net"), ("Btw " + esc(o["settings"]["vat"]) + "%", "vat_amount"), ("Totaal incl. btw", "gross")))
    return f'''<!doctype html><html lang="nl"><meta charset="utf-8"><title>{esc(o["number"])}</title><link rel="stylesheet" href="/static/style.css"><body class="print"><main><p class="eyebrow">Q-HOME · PROJECTBOUW</p><h1>Prijsvoorstel elektriciteit</h1><p>{esc(o["number"])} · {o["created"]}</p><h2>{esc(o["settings"]["project"])}</h2><p>Klant: {esc(o["settings"]["customer"])}</p><p>Geldig: {esc(o["settings"]["validity"])}</p><p class="noprint">Gebruik Afdrukken in je browser om dit voorstel als PDF op te slaan.</p><table><thead><tr><th>Locatie</th><th>Omschrijving</th><th>Aantal</th><th>EH</th><th>EH-prijs</th><th>Totaal</th></tr></thead><tbody>{rows}</tbody></table><section class="totals">{totals}</section><h2>Voorwaarden en afbakening</h2><p style="white-space:pre-wrap">{esc(o["settings"]["conditions"])}</p>{'<h3>Uitgesloten posten</h3><ul>' + exclusions + '</ul>' if exclusions else ''}<p>Bron: {esc(o["filename"])} · {esc(o["sheet"])}</p></main></body></html>'''


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
