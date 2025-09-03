# cli/json2sheet.py
import json, argparse
from spreadsheet_handling.core.flatten import flatten_json
from spreadsheet_handling.core.df_build import build_df_from_records
from spreadsheet_handling.core.refs import add_helper_columns
from spreadsheet_handling.io_backends.excel_xlsxwriter import ExcelBackend 
from spreadsheet_handling.io_backends.csv_backend import CSVBackend

ap = argparse.ArgumentParser()
ap.add_argument("input_json")
ap.add_argument("-o","--output", required=True)
ap.add_argument("--levels", type=int, required=True)
ap.add_argument("--backend", choices=["excel","csv","ods"], default="excel")
ap.add_argument("--config")  # optional: YAML mit Sheet-Definitionen, Referenzen, etc.
args = ap.parse_args()

data = json.load(open(args.input_json))
rows = data if isinstance(data, list) else [data]
records = [flatten_json(r) for r in rows]

# optional: Hilfsspalten aus config
# ref_specs = load_from_config(args.config) ...
# records = add_helper_columns(records, ref_specs)

df = build_df_from_records(records, levels=args.levels)

if args.backend == "excel":
    backend = ExcelBackend()
else:
    backend = CSVBackend()

backend.write(df, args.output, sheet_name="Daten")

