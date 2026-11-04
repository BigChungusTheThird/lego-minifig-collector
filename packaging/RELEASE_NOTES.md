## DC Minifiguren-Sammlung

Sammlungs-App für **Windows und macOS** für LEGO-DC-Minifiguren. Die Daten kommen aus BrickLinks offiziellem
Katalog-Download. Nach dem Import läuft alles **offline**.

### Neu in 1.1

- **Die Sammlung ist jetzt die Hauptansicht.** Schnelles Bilder-Raster oder Tabelle, gruppiert nach Kategorie, Thema
  oder Jahr, mit Fortschritt pro Gruppe.
- **Hab ich, Wunschliste ★, Notizen ✎** pro Figur. Mehrfachauswahl per Strg/⌘ oder Umschalt, Rechtsklick-Menü.
- **Figuren ausblenden:** Was du nicht sammeln willst, verschwindet aus Sammlung, Zählern und Export. Unter
  „Ausgeblendet“ kannst du es jederzeit wieder einblenden.
- **Ø-Verkaufspreis der letzten 6 Monate** über die offizielle BrickLink-API für DACH (DE+AT+CH), EU, Europa,
  Deutschland oder weltweit, neu und gebraucht. Die App zeigt Sammlungswert und Kosten der fehlenden Figuren.
  Dafür brauchst du eigene, kostenlose API-Schlüssel.
- **PDF ist jetzt eine Export-Funktion:** alle / nur fehlende (Fehlliste) / nur gesammelte / Wunschliste, optional
  mit Preis. Dazu kommt ein **CSV-Export** für Excel.
- **Sicherung:** Sammlung als Datei sichern und wiederherstellen.

### Download

| System | Datei |
|---|---|
| Windows 10/11 | `DC-Minifig-Checkliste-Windows.zip` |
| Mac mit Apple-Chip (M1/M2/M3/M4 …) | `DC-Minifig-Checkliste-macOS-AppleSilicon.zip` |
| Mac mit Intel-Prozessor | `DC-Minifig-Checkliste-macOS-Intel.zip` |

**Windows:** ZIP entpacken und `DC-Minifig-Checkliste.exe` starten. Bei „Der Computer wurde durch Windows geschützt“ auf
*Weitere Informationen* → *Trotzdem ausführen* klicken.

**Mac:** ZIP entpacken und die App in „Programme“ ziehen. Beim ersten Start Rechtsklick → *Öffnen* → *Öffnen* wählen.
Falls macOS blockiert: *Systemeinstellungen* → *Datenschutz & Sicherheit* → *Dennoch öffnen*, oder im Terminal
`xattr -dr com.apple.quarantine /Applications/DC-Minifig-Checkliste.app`.

Deine Daten aus Version 1.0 („Hab ich“, ausgeblendete Figuren) werden übernommen.

### Erster Start

1. **Katalog & Daten** → „BrickLink-Download-Seite öffnen“ → anmelden → *Catalog Items* · *Minifigures* ·
   *Category: All* · *Tab-Delimited File* → *Download* → in der App `Minifigures.txt` auswählen.
2. **Sammlung**: abhaken, ausblenden, Notizen.
3. Optional **Preise**: API-Schlüssel eintragen, Region wählen, „Preise laden“.

Bilder und Daten stammen von BrickLink.com und sind nur für den privaten Gebrauch gedacht.
