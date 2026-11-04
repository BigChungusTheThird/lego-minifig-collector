# DC Minifiguren-Checkliste

Desktop-App für **Windows und macOS**. Sie holt alle LEGO-DC-Minifiguren mit Bild aus dem
[BrickLink](https://www.bricklink.com)-Katalog und baut daraus ein **PDF mit allen Figuren im
Raster**, jede mit einem Kästchen zum Abhaken. Die Kästchen kann man im PDF anklicken oder
ausgedruckt mit dem Stift ankreuzen.

## Was auf die Liste kommt

| Drin (Voreinstellung) | Nicht drin |
|---|---|
| Batman I – nur die Figuren von **2008** | **Marvel** (komplett) |
| DC Super Heroes: Batman II, Justice League, Superman, Wonder Woman, Aquaman, … | Figuren von **vor 2008** |
| The LEGO Batman Movie (Set-Figuren) | **DCEU-Filmfiguren**: Man of Steel, Batman v Superman, Wonder Woman (2017/1984), Justice League (2017), Aquaman (2018), Shazam! |
| Sammelfiguren **LEGO Batman Movie Serie 1 & 2**, DC Super Heroes Serie | |
| Mighty Micros | |
| **Ausnahme: Knightmare Batman** (sh0532) bleibt drin | |

Optional zuschaltbar: DC-Figuren aus anderen Themen (The LEGO Movie, Dimensions …),
DC Super Hero Girls, DUPLO und Spiel-Mikrofiguren. Jede einzelne Figur lässt sich
außerdem in Schritt 3 von Hand an- oder abwählen.

## So funktioniert es

1. **Themen & Filter**: Zeitraum und Themen wählen (die Voreinstellung passt schon).
2. **Katalog importieren**: BrickLink stellt angemeldeten Mitgliedern den kompletten
   Minifiguren-Katalog als Datei bereit. Ein kostenloses Konto genügt.
   * In der App auf **„BrickLink-Download-Seite öffnen“** klicken
     (<https://www.bricklink.com/catalogDownload.asp>) und anmelden.
   * Dort wählen: *What to download* „Catalog Items“ · *Item Type* „Minifigures“ ·
     *Category* „All“ · *File Format* „Tab-Delimited File“ · falls angeboten „Year Released“
     ankreuzen → **Download**. Es entsteht `Minifigures.txt`.
   * In der App **„Datei auswählen …“** klicken. Liegt die Datei im Download-Ordner, bietet
     die App sie von selbst an.

   Die App behält nur die DC-Figuren. Sie ordnet sie nach BrickLinks Kategorien zu:
   Batman I, Super Heroes › Batman II / Justice League / Superman / The Batman …,
   Sammelfiguren usw. Marvel-Kategorien fallen weg. In gemischten Kategorien wie
   „Mighty Micros“ oder „Super Heroes Other“ entscheidet der Figurenname. Danach lädt die
   App die Bilder von `img.bricklink.com` (langsam und zwischengespeichert).
3. **Auswahl prüfen**: Tabelle mit Bild-Vorschau. Doppelklick oder Leertaste nimmt eine
   Figur auf die Liste oder herunter. **H** markiert „hab ich schon“; diese Figuren
   sind im PDF vorab abgehakt und grün hinterlegt.
4. **PDF erstellen**: A4/Letter, Hoch- oder Querformat, 3–10 Figuren pro Zeile,
   gruppiert nach Kategorie, Thema oder Jahr. Das PDF hat Lesezeichen pro Gruppe und
   pro Gruppe ein Feld „gesammelt: __ / N“.

Den Katalog kannst du jederzeit neu herunterladen und importieren, etwa wenn neue Sets
erscheinen. Deine „Hab ich schon“-Markierungen und Änderungen von Hand bleiben dabei erhalten.

### DCEU-Erkennung

Als DCEU-Filmfiguren gelten die BrickLink-Kategorien *Man of Steel*, *Dawn of Justice*,
*Batman v Superman*, *Wonder Woman* (2017), *Wonder Woman 1984* und *Aquaman* (2018), dazu die
2017er Einträge in *Justice League* (Filmsets 76085–76087) und Shazam sh0586 (Polybag 30623).
Ausnahmen: **Knightmare Batman sh0532** bleibt drin, ebenso der Comic-Aquaman sh0533.

## Hinweis zum BrickLink-Bot-Schutz

BrickLinks Katalog-Listen im Web (`catalogList.asp`) verlangen inzwischen eine
Browser-Prüfung (AWS WAF). Die App liest diese Seiten deshalb nicht automatisch aus und
umgeht die Prüfung nicht. Sie nutzt stattdessen den offiziellen Katalog-Download, den du
selbst im Browser holst. Die Figurenbilder auf `img.bricklink.com` sind frei abrufbar.

## Download

Die fertigen Programme baut GitHub Actions bei jedem Push:
**Actions → Build → neuester Lauf → Artifacts**

* `DC-Minifig-Checkliste-Windows.zip`: `.exe`, einfach starten
* `DC-Minifig-Checkliste-macOS-AppleSilicon.zip`: für M1/M2/M3/M4-Macs
* `DC-Minifig-Checkliste-macOS-Intel.zip`: für ältere Intel-Macs

Hinweise zum ersten Start (Windows SmartScreen / macOS Gatekeeper) stehen in
[`packaging/LIESMICH.txt`](packaging/LIESMICH.txt). Mit einem Tag `v1.0.0` erzeugt der
Workflow automatisch ein GitHub-Release mit allen drei Downloads.

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
python app.py --cli pdf Liste.pdf                        # PDF erzeugen
```

Selbst bauen: `pip install pyinstaller && python packaging/build.py`, das Ergebnis liegt in `dist/`.

## Daten

Einstellungen, Katalog, Sammlung (`collection.json`) und Zwischenspeicher liegen unter
`%APPDATA%\DC-Minifig-Checkliste` (Windows) bzw.
`~/Library/Application Support/DC-Minifig-Checkliste` (macOS).

Bilder und Daten stammen von BrickLink.com und sind nur für den privaten Gebrauch gedacht.
LEGO, BrickLink und DC sind Marken ihrer jeweiligen Inhaber; dieses Projekt steht mit
ihnen in keiner Verbindung.
