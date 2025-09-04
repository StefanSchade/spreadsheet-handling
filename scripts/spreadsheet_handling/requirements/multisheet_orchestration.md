# Zielbild (kurz)

Ein Orchestrator baut aus mehreren JSON-Quellen ein Workbook mit mehreren Blättern (Pack) und erzeugt aus einem Workbook wieder ein Verzeichnis mit JSON-Dateien (Unpack). Fremdschlüssel (FK) können konfiguriert oder per Konvention erkannt werden. Lesbare Helper-Spalten werden beim Packen automatisch erzeugt (und beim Unpack ignoriert), optional als Excel-Formeln (VLOOKUP/Data Validation) für bessere UX. Defaults erlauben den Betrieb ohne YAML, YAML wird nur gebraucht, wenn’s komplexer wird. Die bestehende Logik zu Levels/Flatten/Unflatten bleibt die Grundlage.

## Grundlegende Festlegngen

* ein Blatt entspricht immer einer Tablelle - diese muss nicht in Normalform vorliegen - aber 2 Tabellen nebeneinander (in einem Spreadsheet moeglich) sind nicht vorgesehen

* Wir wollen ein Entwicklungs-Tool bauen, kein Consumer Produkt. Im Zweifel sticht "Keep it simple" den Wunsch nach einer "idiotensicheren" Loesung.

# CLI-Design

## Zwei neue Entry Points:

```bash
sheets-pack --config config.yaml oder sheets-pack <json_dir> -o <workbook>

sheets-unpack <workbook> -o <json_dir> [--levels 3]
```

Die bestehenden Tools `json2sheet`/`sheet2json` bleiben für Single-Sheet-Fälle; `sheets-pack`/`sheets-unpack` werden mehrere Sheets orchestrieren. Sie bekommen jeweils einen eigenen Eintrag in `pyproject.yml` analog zu `json2sheet` / `sheet2json`.

## Steuerung per Kommandozeile vs. Konfigurations-YAML 

Für Fälle mit sehr einfacher Struktur kann der Prozess über Kommandozeilenargumente gesteuert werden. Ab einer gewissen Komplexität wird die Konfiguration über ein YAML notwendig. Es ist wichtig, das Kommandozeilenparsing nicht zu komplex werden zu lassen. Ich denke dass die Abrenzung sinnvollerweise nicht entlang der Features laufen sollte, sondern über die Frage wie komplex das jeweilige Konifgurationsziel ist. Eine wichtige Frage hierbei ist mutmaßlich die Frage ob alle Blätter einer Mappe gleich konfiguriert werden, oder ob es eine Konfiguration pro Blatt gibt.

### Features die auf jeden Fall ueber die Kommandozeile konfiguriert werden koennen (das bedeutet nicht, dass man nicht eine Konfiguration ueber das YML bereitstellen kann)

* Wahl der Spreadsheet Engine (xls, ods, csv -> default xls)

### Features die sinnvoll über die Kommandozeile kofiguriert werden können, wenn alle Blätter die gleiche Konfiguration brauchen - wenn man eine Konfiguration pro Blatt 

* Zahl der Header-Level

* Welche Spaltenueberschrift markiert die ID (Key) der Tabelle (Default ID)

* Welche Spaltenueberschriften markieren die Helper-Spalten der jeweiligen Tabelle (Default name)

* Alle Blatter einer Mappe werden verarbeitet - die Blattnamen korrespondieren mit den Filenamen ueber Kommandozeile - ausdrueckliche Konfiguration der einzelnen zu verarbeitenden Blaetter ueber YAML implizites feature da dort ja fuer jedes Blatt eine Konfiguration der einzelnen Parameter vorliegen muss - hier auch konfigurierbares Mapping Blattname-Filname moeglich (siehe YAML Entwurf unten)

### Non-Essential Features nur über YAML einfach um das CLI parsing zu begrenzen

* style Vorgaben vgl YAML Entwurf unten

* Konfiguration von excel formeln, datenvalidierungen etc.

### Features die ausschliesslich ueber das YML konfigurierbar sein sollten, weil man sich damit schnell ein bein stellen kann

* Veraenderung des Default prefixes ("_") der Helper Spalten

* Veranederung des patterns mit dem die IDs fremder Tabellen markiert werden Identifikator_(Tabellenname)

* Switch ob die Spaltenkennzeichen (Name, ID etc. case sensitiv gematcht werden sollten - default Nein)

* Die Richtung des Datenflusses Workbook <-> JSON ergibt sich durch die Wahl des scripts (siehe oben)
 

### YAML-Schema (v1)

```yaml
workbook: scripts/spreadsheet_handling/tmp/tmp.xlsx

defaults:
  levels: 3
  id_field: "id"
  helper_prefix: "_"         # wird beim Unpack gedroppt
  detect_fk: true            # Konventionelle FK-Erkennung aktivieren
  fk_header_pattern: "ID_{sheet}"   # z. B. ID_Kunden
  backend: "xlsx"            # xlsx|csv|ods (ods später)

sheets:
  - name: Kunden
    json: data/kunden.json   # Datei ODER Verzeichnis (pattern s.u.)
    levels: 3
    # optionale Stil-/UX-Hinweise (xlsx only; nice-to-have):
    style:
      freeze_header: true
      color_headers: true
      width_auto: true

  - name: Bestellungen
    json: data/bestellungen.json
    levels: 3
    # FK-Definitionen (überschreiben Defaults / Konventionen)
    fks:
      - column: "bestellung.kunde.id"     # Pfad in diesem Sheet
        targets:
          sheet: "Kunden"                 # Zielblatt
          id_field: "kunde.id"            # Pfad im Zielobjekt (Default: defaults.id_field)
          label_field: "kunde.name"       # menschenlesbar
        helper:
          display_column: "_kunde_name"   # Spaltenname im Sheet
          excel_formula: true             # VLOOKUP statt statischem Text (xlsx)
          data_validation: true           # nur existierende IDs auswählbar (xlsx)
    # Zusätzlich rein "lokale" Helper-Spalten (ohne FK)
    helpers:
      - source_path: "bestellung.summe"   # beliebige Quelle im selben Objekt
        display_column: "_summe_anzeige"
```

Hinweise zum YAML Entwurf:

* ich sehe eine redundanz bei `label_field` und `display_column`. Ich stelle mir das so vor, dass der Spaltenname (bzw. die Spalennamen falls es 2 sind) in der Ursprungstabelle des Datensatzes konfigurierbar ist (default Name) der  als helper in die andere Tabelle gemappt wird - dort wird _ vorangestellt um das als helper zu markieren - vielleicht auch der Blattname des ursprungssatzes um explizit zu sein. Beispiel: Der ORT wird 2x als ID in den Weg gemappt (Start ort End Ort) mit einer ID - das ist vermutlich innerhalb einer substruktur .... from: {location_ID: ORT 001}, to: {location_ID: ORT_002} ... in der excel tabelle sollten an dieser stelle der ORTSNAME und der REGIONENNAME (also insgesammt 4 Spalten) hinzugemappt werden. z.b. _from_location_ortsname _from_location_regionname _to_location_ortsname _to_location_regionname damit der Bearbeiter weiss mit welchen Orten er es zu tun hat. wir muessen also bei den helper spalten trennen Name in der ursprungs-Tabelle -> default name, ansonsten konfigurierbar - auch 2 stueck - name in der zieltabelle ergibt sich durch voranstellung des _ und multilevel pfad des ID - Feldes (das liegt unter from bzw. to)


### Konventionen/Defaults (wenn kein YAML) und kein override ueber komandozeile

Alle *.json in einem Verzeichnis → je Datei ein Blatt mit Blattname = Dateiname ohne Endung.

levels: 3, id_field: id, helper_prefix: _.


Quellen laden: je Sheet Datei oder Verzeichnis lesen; pro JSON Objekt → flatten_json(...) → build_df_from_records(levels). Spaltenreihenfolge folgt „first-seen“ (dein Test sichert das bereits), das übernehmen wir unverändert.

Helper-Spalten verwerfen: Alle Spalten, deren oberster Segmentname mit helper_prefix beginnt, werden nicht zurückgeschrieben (deine unflatten.row_to_obj macht das heute schon anhand _—das behalten wir exakt so).

### Validierung (optional):

Fehlende FK-Ziele → Warnung/Fehler gemäß fail_on_missing_fk: true|false.

Doppelte IDs in Zieltabellen → Warnung/Fehler.

Schreiben: je Blatt in <out>/<sheet>.json. Keine Loeschlogik wegen Keep it spimple - das erfolgt in einem esternen Bash skript

### Edge Cases & Fehlerbilder

Neue Zeilen ohne ID: Option autogen_ids: uuid|seq|none (per Blatt). seq kann ein Template KND-{0001} haben.

Benennungen geändert: Wenn der Nutzer Kopfzeilen editiert, behandeln wir das bewusst tolerant:

Unbekannte Spalten → werden als normale Daten behandelt.

Entfernte FK-Spalte → es entfällt die Validierung/Helper-Logik für diesen Pfad.

Mehrere Tabellen in einem Blatt: Aus Scope v1 raus (zu fehleranfällig). Empfehlung: ein JSON ⇄ ein Blatt. (Später könnten „Block-Delimiter“ pro Blatt kommen.)

Umsetzungsfahrplan
Phase 1 — MVP (Konfig & Orchestrierung, ohne Excel-Formeln)

CLI: sheets-pack/sheets-unpack + pyproject Einträge.

Config-Parser mit Defaults & „no-YAML“-Modus (Dir→Workbook).

Pack: Mehrere JSON → mehrere Blätter, Helper-Spalten als statische Strings (kein VLOOKUP).

Unpack: Mehrere Blätter → mehrere JSON, _-Spalten werden gedroppt (ist schon Teil deiner Unflatten-Logik).

Tests:

Roundtrip über zwei Blätter mit FK (CSV & XLSX), inkl. Unicode (an Test test_csv_roundtrip_unicode_and_multirow angelehnt).

First-seen-Order bleibt erhalten.

Phase 2 — FK-Komfort & Validierung

FK-Resolver (Konvention + YAML).

Validierung: fehlende FK, doppelte IDs.

Option --fail-on-warn für CI/strict.

Phase 3 — Excel-UX (VLOOKUP & Data Validation)

Named Ranges je Sheet (IDs und Labels).

Helper-Spalten als Formeln (VLOOKUP/XLOOKUP je nach Writer).

Dropdowns (Data Validation) für FK-Spalten.

Stil: Freeze Header, Farben, Spaltenbreite, „readonly“ Format für Helper.

Phase 4 — IDs & Generatoren

autogen_ids (uuid/seq/template) + Kollisionsschutz.

Phase 5 — ODS-Backend & Multi-Sheet-Read/Write

ODS (odfpy) implementieren, BackendBase.read_multi/write_multi konkretisieren (heute schon als Hooks vorhanden).

Teststrategie (prägnant)

Unit: FK-Parsing aus YAML & Konvention; Helper-Spalten-Erzeugung; Validierungsfunktionen.

E2E: sheets-pack → sheets-unpack ergibt inhaltlich gleiche JSONs (bis auf Ordnung & Hilfsspalten).

Backends: CSV und XLSX Roundtrips (CSV nutzt bereits N-zeilige Header).

Beispiel-Config (etwas größer)
workbook: build/world.xlsx

defaults:
  levels: 3
  id_field: "id"
  helper_prefix: "_"
  detect_fk: true
  fk_header_pattern: "ID_{sheet}"
  backend: "xlsx"

sheets:
  - name: Orte
    json: data/orte.json

  - name: Charaktere
    json: data/charaktere.json
    fks:
      - column: "charakter.heimat.id"
        targets:
          sheet: "Orte"
          id_field: "ort.id"
          label_field: "ort.name"
        helper:
          display_column: "_heimat_name"
          excel_formula: true
          data_validation: true

  - name: Gruppen
    json: data/gruppen.json
    helpers:
      - source_path: "gruppe.beschreibung"
        display_column: "_beschreibung_preview"

Warum passt das zu deinem bestehenden Code?

Multi-Level-Header / Levels: bauen auf deiner aktuellen Flatten/Build-DF Logik auf.

Helper-Spalten droppen: deine unflatten.row_to_obj ignoriert Spalten mit _ bereits heute. Wir nutzen denselben Prefix konfigurierbar.

CSV-Backend kann Header mit N Ebenen schreiben/lesen → ideal für Tests & CI ohne Excel.

Backend-Hooks write_multi/read_multi existieren schon als Default-Implementierung → wir erweitern für XLSX ein echtes Multi-Sheet-Write.

Spaltenreihenfolge „first-seen“ ist mit Test abgesichert → übernehmen.

Nächste Schritte (konkret & klein anfangen)

CLI-Skeleton cli/sheets_pack.py & cli/sheets_unpack.py + pyproject-Einträge. (Nur JSON-Dir ⇄ Workbook, keine FKs.)

YAML-Parser + Defaults, Mapping Datei/Blatt, levels.

FK-Konvention (ID_{sheet}) + statische Helper-Spalten.

E2E-Tests (CSV & XLSX).

Optional: Strict-Modus/Validierung.

Danach Phase-3-Goodies (VLOOKUP/Validation/Styles) gezielt ergänzen.

Wenn du willst, skizziere ich dir im nächsten Schritt die Modul-/Funktionssignaturen (reine Stubs) für sheets_pack.py/sheets_unpack.py und eine minimale Testdatei, damit du sofort grün durchstartest—ohne gleich in die Tiefe zu gehen.
