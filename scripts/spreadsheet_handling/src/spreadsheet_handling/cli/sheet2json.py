# cli/sheet2json.py
import json, argparse
from spreadsheet_handling.core.unflatten import df_to_objects
from spreadsheet_handling.io_backends.excel_xlsxwriter import ExcelBackend
from spreadsheet_handling.io_backends.csv_backend import CSVBackend  

ap = argparse.ArgumentParser()
ap.add_argument("input_sheet")
ap.add_argument("-o","--output", required=True)
ap.add_argument("--levels", type=int, required=True)
ap.add_argument("--backend", choices=["excel","csv","ods"], default="excel")
args = ap.parse_args()

if args.backend == "excel":
    backend = ExcelBackend()
elif args.backend =="ods":
    backend = ODSBackend()
else:
    backend = CSVBackend()

df = backend.read(args.input_sheet, header_levels=args.levels, sheet_name="Daten")

objs = df_to_objects(df)
res = objs if len(objs) > 1 else (objs[0] if objs else {})
json.dump(res, open(args.output,"w"), ensure_ascii=False, indent=2)

