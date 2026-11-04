# DC Minifiguren-Sammlung

Desktop-App für **Windows und macOS** zum Verwalten einer LEGO-DC-Minifiguren-Sammlung.
Die Daten kommen aus dem [BrickLink](https://www.bricklink.com)-Katalog. Einmal importiert
(Katalog und Bilder), läuft die App **komplett offline**.

* **Sammlung als Bilder-Raster** (oder Tabelle), gruppiert nach Kategorie, Thema oder Jahr,
  jede Gruppe mit Fortschrittsbalken („28 / 158 · 18 %“)
* **Hab ich** per Kästchen, Doppelklick oder Leertaste. Mit Strg/⌘ oder Umschalt wählst du
  mehrere Figuren gleichzeitig aus.
* **Wunschliste** ★, **Notizen** ✎ pro Figur
* **Ausblenden**: Figuren, die du nicht sammeln willst, verschwinden aus Sammlung, Zählern und
  Export. Unter „Ausgeblendet“ lassen sie sich jederzeit wieder einblenden.
* **Ø-Verkaufspreis der letzten 6 Monate** pro Figur (BrickLink-API) für **DACH**, **EU**,
  Europa, Deutschland oder weltweit, neu und gebraucht. Die App zeigt den Sammlungswert und
  was die fehlenden Figuren ungefähr kosten.
* **Export**: PDF-Checkliste im Raster (alle / nur fehlende / nur gesammelte / Wunschliste)
  und CSV für Excel/Numbers
* **Sicherung**: Die Sammlung lässt sich als Datei sichern und auf einem anderen Rechner wiederherstellen.

## Was zur Sammlung gehört (Voreinstellung)

| Drin | Nicht drin |
|---|---|
| Batman I, nur die Figuren von **2008** | **Marvel** (komplett) |
| DC Super Heroes: Batman II, Justice League, Superman, Wonder Woman, Aquaman, The Batman, … | Figuren von **vor 2008** |
| The LEGO Batman Movie (Set-Figuren) | **DCEU-Filmfiguren**: Man of Steel, Batman v Superman, Wonder Woman (2017/1984), Justice League (2017), Aquaman (2018), Shazam! |
| Sammelfiguren **LEGO Batman Movie Serie 1 & 2**, DC Super Heroes Serie | |
| Mighty Micros | |
| **Ausnahme: Knightmare Batman** (sh0532) bleibt drin | |

DC-Figuren aus anderen Themen (The LEGO Movie, Dimensions …), DC Super Hero Girls, DUPLO und
Spiel-Mikrofiguren lassen sich unter „Themen & Filter“ zuschalten. Jede einzelne Figur kannst du
in der Sammlung aus- oder einblenden.

## Bedienung

| Bereich | Wofür |
|---|---|
| **Sammlung** | Hauptansicht: suchen, filtern (Alle / Hab ich / Fehlen mir / Wunschliste / Mit Notiz / Ausgeblendet), abhaken, Notizen, Preise |
| **Themen & Filter** | Zeitraum, Themen, DCEU-Ausschluss, Knightmare-Ausnahme |
| **Katalog & Daten** | BrickLink-Katalog importieren, Bilder für den Offline-Betrieb laden, Sicherung |
| **Preise** | BrickLink-API-Schlüssel, Region (DACH/EU/…), Preise laden |
| **PDF & Export** | PDF-Checkliste und CSV |

**Tastatur & Maus in der Sammlung:** Kästchen anklicken, Doppelklick oder Leertaste schaltet
„Hab ich“ um. Strg/⌘-Klick nimmt eine Figur zur Auswahl dazu, Umschalt-Klick wählt einen
Bereich, Strg/⌘+A alle angezeigten. Die Pfeiltasten wechseln die Figur, ein Rechtsklick öffnet das Menü.

### 1. Katalog importieren (einmalig, online)

1. Unter **Katalog & Daten** auf „BrickLink-Download-Seite öffnen“ klicken und anmelden
   (kostenloses Konto). Die Seite ist <https://www.bricklink.com/catalogDownload.asp>.
2. Dort wählen: *Catalog Items* · *Minifigures* · *Category „All“* · *Tab-Delimited File* ·
   falls angeboten „Year Released“ ankreuzen → **Download** (`Minifigures.txt`).
3. In der App die Datei auswählen. Liegt sie im Download-Ordner, bietet die App sie direkt an.
   Danach lädt die App die Bilder von `img.bricklink.com` und speichert sie lokal.

Die App behält nur die DC-Figuren und ordnet sie über BrickLinks Kategorien zu. In gemischten
Kategorien wie „Mighty Micros“ oder „Super Heroes Other“ entscheidet der Figurenname. Einen
neueren Katalog kannst du jederzeit importieren. „Hab ich“, Wunschliste, Notizen und
Ausblendungen bleiben dabei erhalten.

### 2. Preise (optional, online)

Die Preise kommen aus der **offiziellen BrickLink-API** (Price Guide, *Last 6 Months Sales*).
Dafür brauchst du eigene, kostenlose API-Schlüssel:

1. Bei BrickLink anmelden und die API-Seite öffnen (Knopf in der App).
2. Einen *Consumer Key* registrieren und einen *Access Token* erstellen. Als IP-Adresse
   und Maske jeweils `0.0.0.0` eintragen, dann funktioniert der Token auch mit wechselnder
   Internet-Adresse. BrickLink kann für den API-Zugang ein Verkäuferprofil verlangen.
3. Die vier Werte (Consumer Key/Secret, Token Value/Secret) unter **Preise** eintragen,
   „Verbindung testen“, dann „Preise laden“.

* **DACH** fragt Verkäufe in DE, AT und CH ab und gewichtet sie nach verkaufter Menge
  (3 Abfragen pro Figur und Zustand). **EU** und **Europa** nutzen BrickLinks Regionen.
* BrickLink erlaubt 5.000 API-Abfragen pro Tag. Die App stoppt rechtzeitig, und der nächste
  Lauf macht weiter. Zuerst kommen die Wunschliste und die fehlenden Figuren dran.
* Preise werden gespeichert (offline sichtbar) und erst nach der eingestellten Zeit erneuert.
* Die Schlüssel liegen nur lokal im Datenordner (`bricklink_api.json`).

### 3. Export

PDF-Checkliste im Raster mit anklickbaren Kästchen, Lesezeichen und „gesammelt: __ / N“ pro
Gruppe. Wahlweise enthält sie alle Figuren, nur fehlende (Fehlliste), nur gesammelte oder die
Wunschliste, auf Wunsch mit Ø-Preis. Der CSV-Export enthält alle Daten inkl. Preisen und
Notizen. Er ist durch Semikolons getrennt und öffnet sich direkt in deutschem Excel.

## Hinweis zum BrickLink-Bot-Schutz

BrickLinks Katalog-Listen im Web (`catalogList.asp`) verlangen eine Browser-Prüfung (AWS WAF).
Die App liest diese Seiten nicht automatisch aus und umgeht die Prüfung nicht. Sie nutzt den
offiziellen Katalog-Download, die frei abrufbaren Bilder und die offizielle API.

## Download

Die fertigen Programme liegen unter **[Releases](https://github.com/BigChungusTheThird/lego-minifig-collector/releases/latest)**:

* `DC-Minifig-Checkliste-Windows.zip`: `.exe` für Windows 10/11
* `DC-Minifig-Checkliste-macOS-AppleSilicon.zip`: für Macs mit M1/M2/M3/M4
* `DC-Minifig-Checkliste-macOS-Intel.zip`: für ältere Intel-Macs

Hinweise zum ersten Start (Windows SmartScreen / macOS Gatekeeper) stehen in
[`packaging/LIESMICH.txt`](packaging/LIESMICH.txt).

Ein neues Release entsteht auf drei Wegen: über einen Tag `v…` per Push, über *Actions* →
*Build* → *Run workflow* mit Tag-Eingabe oder über einen Push mit `[release]` in der
Commit-Nachricht. Im letzten Fall nimmt der Workflow die Version aus `APP_VERSION` in
`dcchecklist/config.py`.

## Aus dem Quellcode starten

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Kommandozeile (ohne Oberfläche):

```bash
python app.py --cli import ~/Downloads/Minifigures.txt   # Katalog importieren + Bilder laden
python app.py --cli list --all                           # alle Figuren mit Entscheidung
python app.py --cli pdf Fehlliste.pdf --scope missing    # PDF (all|missing|owned|wishlist)
```

Tests: `pip install pytest && python -m pytest`. Selbst bauen:
`pip install pyinstaller && python packaging/build.py`, das Ergebnis liegt in `dist/`.

## Daten

Einstellungen, Katalog, Sammlung (`collection.json`), Preise (`prices.json`), API-Schlüssel
und Bilder liegen unter `%APPDATA%\DC-Minifig-Checkliste` (Windows) bzw.
`~/Library/Application Support/DC-Minifig-Checkliste` (macOS).

Bilder und Daten stammen von BrickLink.com und sind nur für den privaten Gebrauch gedacht.
LEGO, BrickLink und DC sind Marken ihrer jeweiligen Inhaber; dieses Projekt steht mit
ihnen in keiner Verbindung.
