# Smoke Test: Flat vs. Nested JSON Roundtrip
#
# Dieses Verzeichnis enthaelt 3 Szenarien:
#
# in_flat/       Flache Records (kein Nesting) - funktioniert heute komplett
# in_nested_1/   1 Ebene Nesting: items[] Array - items wird als JSON-String in Zelle gespeichert
# in_nested_2/   2 Ebenen Nesting: items[].extras[] + customer.address - zeigt Grenzen
#
# Ausfuehrung (PowerShell, aus spreadsheet-handling/):
#
#   $env:PYTHONPATH = "src"
#
#   # Szenario 1: Flach (roundtrip-safe)
#   .venv_win\Scripts\python -m spreadsheet_handling.cli.apps.sheets_pack interactive_test\smoke_nested\in_flat -o tmp\smoke_flat.xlsx
#   .venv_win\Scripts\python -m spreadsheet_handling.cli.apps.sheets_unpack tmp\smoke_flat.xlsx -o tmp\smoke_flat_out
#
#   # Szenario 2: 1 Ebene Nesting
#   .venv_win\Scripts\python -m spreadsheet_handling.cli.apps.sheets_pack interactive_test\smoke_nested\in_nested_1 -o tmp\smoke_nested1.xlsx
#   .venv_win\Scripts\python -m spreadsheet_handling.cli.apps.sheets_unpack tmp\smoke_nested1.xlsx -o tmp\smoke_nested1_out
#
#   # Szenario 3: 2 Ebenen Nesting
#   .venv_win\Scripts\python -m spreadsheet_handling.cli.apps.sheets_pack interactive_test\smoke_nested\in_nested_2 -o tmp\smoke_nested2.xlsx
#   .venv_win\Scripts\python -m spreadsheet_handling.cli.apps.sheets_unpack tmp\smoke_nested2.xlsx -o tmp\smoke_nested2_out
#
# Dann die XLSX Dateien in Excel oeffnen und die JSON Ausgabe vergleichen.
