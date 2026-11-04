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

1. **Themen & Filter**: Zeitraum und Themen wählen.
2. **Katalog laden**: Die App liest BrickLinks Liste *„DC Comics Co-Branded Items“*
   (`promoCatID=247`), und zwar Jahr für Jahr ab 2008. So sind Marvel und alte Figuren
   gar nicht erst dabei. Danach folgt eine Gegenprüfung über die DC-Kategorien. Zum
   Schluss liest sie die Inventare der DCEU-Sets, um die Filmfiguren zu erkennen.
   BrickLink wird absichtlich langsam abgefragt (1–2 s Pause pro Seite), und alles
   wird zwischengespeichert.
3. **Auswahl prüfen**: Tabelle mit Bild-Vorschau. Doppelklick oder Leertaste nimmt eine
   Figur auf die Liste oder herunter. **H** markiert „hab ich schon“; diese Figuren
   sind im PDF vorab abgehakt und grün hinterlegt.
4. **PDF erstellen**: A4/Letter, Hoch- oder Querformat, 3–10 Figuren pro Zeile,
   gruppiert nach Kategorie, Thema oder Jahr. Das PDF hat Lesezeichen pro Gruppe und
   pro Gruppe ein Feld „gesammelt: __ / N“.

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
python app.py --cli fetch            # Katalog + Bilder laden
python app.py --cli list --all       # alle Figuren mit Entscheidung anzeigen
python app.py --cli pdf Liste.pdf    # PDF erzeugen
python app.py --cli smoke --dump     # Live-Test der BrickLink-Parser
```

Selbst bauen: `pip install pyinstaller && python packaging/build.py`, das Ergebnis liegt in `dist/`.

## Daten

Einstellungen, Katalog, Sammlung (`collection.json`) und Zwischenspeicher liegen unter
`%APPDATA%\DC-Minifig-Checkliste` (Windows) bzw.
`~/Library/Application Support/DC-Minifig-Checkliste` (macOS).

Bilder und Daten stammen von BrickLink.com und sind nur für den privaten Gebrauch gedacht.
LEGO, BrickLink und DC sind Marken ihrer jeweiligen Inhaber; dieses Projekt steht mit
ihnen in keiner Verbindung.
