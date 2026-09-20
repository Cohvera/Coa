# Cohvera Coa · Q-Home Offer Assistant

Q-Home-module voor elektriciteitsoffertes in projectbouw: XLSX importeren, aantallen en prijskoppelingen controleren, projectinstellingen invullen en een prijsvoorstel bewaren. All-in verkoopprijzen per post, exclusief btw, worden centraal beheerd.

## Starten met Docker Compose

1. Kopieer `.env.example` naar `.env` en stel twee verschillende sterke wachtwoorden in.
2. `docker compose up -d --build`
3. Open het bestaande Coa-portaal op http://localhost:3000 of de offertemodule op http://localhost:8000.
4. Meld aan met het beheerderswachtwoord voor prijsbeheer of het calculatiewachtwoord voor offertes.

De module gebruikt Python/FastAPI, standaardbibliotheek SQLite en gewone HTML/CSS/JavaScript. Geen extra frontendframework. Het Python-basisimage ondersteunt Linux AMD64 en ARM64. De database staat in het persistente volume `qhome-data`; neem dit mee in backups. Gebruik HTTPS bij externe toegang en zet dan `QHOME_SECURE_COOKIE=1`. De module deelt één Q-Home-werkruimte tussen gebruikers; dit is geen multitenant autorisatiesysteem. Wachtwoordwijzigingen beëindigen bestaande sessies niet; sessies verlopen na twaalf uur.

## Werkwijze

- Upload een `.xlsx` (max. 10 MB), selecteer het gewenste werkblad en controleer kolomletters en eerste detailrij. Een veelgebruikte elektriciteitsmeetstaatopmaak wordt herkend. Andere bestanden krijgen een handmatige kolomtoewijzing.
- De import bewaart bronrij, omschrijving, hoofdstuk, appartementgroep, context, bronhoeveelheid en eenheid. Hoeveelheden worden **niet** automatisch vermenigvuldigd met appartementaantallen. Een dubbel stopcontact blijft één post met een eigen all-in prijs.
- Formules worden nooit uitgevoerd. Een opgeslagen Excel-uitkomst wordt gelezen; zonder uitkomst blijft een formulehoeveelheid een aandachtspunt. Herbereken zulke bestanden in Excel of vul de hoeveelheid bewust in.
- Koppeling gebeurt op exacte omschrijving/herkenningsnaam en eenheid. Geen gokprijzen of fuzzy automatische matches. Keuringen en as-built posten met dezelfde korte omschrijving behouden hun context in de koppeling.
- De startprijslijst bevat enkele gebruikelijke posten met **lege prijzen**. Een beheerder kan onbekende geïmporteerde posten toevoegen aan de prijslijst en er eigen prijzen invullen. Onbekende eenheden moeten eerst worden aangevuld.
- Wijzig hoeveelheid of eenheid waar nodig, koppel handmatig een prijspost, of sluit een regel uit met reden. Nieuwe prijzen worden gebruikt bij het opnieuw berekenen van een concept.
- Vul project, klant, korting, vaste projectkosten, btw, geldigheid en offertevoorwaarden in. Controleer de bronnotities, oorspronkelijke meetstaat en plannen. Notities uit het klantbestand zijn gegevens, geen instructies voor de software, en worden niet automatisch contractvoorwaarden.
- Alle inbegrepen regels moeten een geldige hoeveelheid, passende eenheid en actieve prijspost met prijs hebben. Vul expliciet 0 in voor een gratis post; leeg betekent onbekend. Een gedeeltelijke calculatie wordt als bekend deelbedrag aangeduid.
- Bevestig de controle en bewaar het prijsvoorstel. De prijzen en instellingen worden als een onveranderlijke momentopname opgeslagen. Download CSV of gebruik de afdrukfunctie van de browser voor PDF. Er wordt niets automatisch verstuurd.

Berekening: per regel aantal × eenheidsprijs, afgerond op eurocenten (half omhoog). Korting wordt afgerond over de som van de regels. Vaste kosten worden daarna toegevoegd. Btw wordt afgerond over het nettototaal. Voorbeeld: 3 × €12,35 = €37,05; 10% korting = €3,71; €5 vaste kosten → €38,34 excl. btw; 21% btw = €8,05 → €46,39.

## Lokale ontwikkeling en tests

Gebruik Python 3.12+ in een virtualenv, installeer `qhome/requirements.txt` en voor tests `httpx==0.28.1`.

Vanuit `qhome/`, met `QHOME_ADMIN_PASSWORD` en eventueel `QHOME_USER_PASSWORD` ingesteld:

```sh
uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m compileall app
python -m unittest discover -s tests -v
```

Optioneel: stel `QHOME_SAMPLE_XLSX` in op een lokale elektriciteitsmeetstaat voor een aanvullende importtest. Klantbestanden, projectnamen, specifieke hoeveelheden en ontwikkeldata worden niet in Git opgenomen.

```sh
docker compose up -d --build
curl -f http://localhost:8000/
```

## Bestaande repository en integratie

De aangeleverde `main` (dc3de6b) bevatte een statisch Cohvera Pulse-dashboard en een onvolledige, losstaande PostgreSQL-API (onder meer `db.js`, migraties en een server-Dockerfile ontbreken). Het dashboard blijft behouden en linkt naar de nieuwe Q-Home-module. De onafgewerkte API staat achter Compose-profiel `legacy-api`, zodat die de start van de module niet blokkeert. De bestaande API is niet gerepareerd of vervangen.

Voor een bestaande reverse proxy kunnen portaal en module onder afzonderlijke hostnamen worden geplaatst. Bouw het portaal dan met `VITE_QHOME_URL` op de module-URL. Er is geen SSO-koppeling omdat de aangeleverde code geen bestaand authenticatiesysteem heeft.

Deze eerste versie verwerkt één gekozen werkblad per calculatie. Samengevoegde aanvragen uit meerdere tabbladen, terugschrijven in de oorspronkelijke klant-Excel, oude `.xls`-bestanden, automatische stuklijstgeneratie en mailverzending vallen buiten deze versie. Uploadbestanden worden na 24 uur bij een volgende upload opgeruimd; conceptregels en voorstellen blijven in SQLite staan.
