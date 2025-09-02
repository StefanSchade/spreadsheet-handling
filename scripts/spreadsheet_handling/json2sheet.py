#!/usr/bin/env python3

import argparse, json, pandas as pd, os

def flatten(obj, parent=None, sep="."):
    items = {}
    if isinstance(obj, dict):
        for k,v in obj.items():
            key = k if parent is None else f"{parent}{sep}{k}"
            items.update(flatten(v, key, sep))
    elif isinstance(obj, list):
        items[parent] = json.dumps(obj, ensure_ascii=False)
    else:
        items[parent] = obj
    return items

def main():
    ap = argparse.ArgumentParser(description="Convert JSON to spreadsheet with N header rows. Shorter paths leave lower header rows empty.")
    ap.add_argument("input", help="Input JSON (object or array of objects)")
    ap.add_argument("-o","--output", default="out.xlsx", help="Output spreadsheet (.xlsx)")
    ap.add_argument("--levels", type=int, required=True, help="Number of header rows to create")
    args = ap.parse_args()

    data = json.load(open(args.input, "r", encoding="utf-8"))
    rows = data if isinstance(data, list) else [data]
    flat_rows = [flatten(r) for r in rows]

    all_cols = sorted(set(k for r in flat_rows for k in r.keys()))
    tuples = []
    for path in all_cols:
        segs = path.split(".")
        if len(segs) >= args.levels:
            head = segs[:args.levels-1]
            tail = ".".join(segs[args.levels-1:])
            segs = head + [tail]
        else:
            segs = segs + [""]*(args.levels - len(segs))
        tuples.append(tuple(segs))

    mi = pd.MultiIndex.from_tuples(tuples)
    df = pd.DataFrame([{c: r.get(c, "") for c in all_cols} for r in flat_rows])
    df.columns = mi
    
    out = args.output
    if not out.lower().endswith(".xlsx"):
        out = os.path.splitext(out)[0] + ".xlsx"
    
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        try:
            # bevorzugt ohne Index (kann bei MultiIndex-Spalten scheitern)
            df.to_excel(writer, index=False, header=True, sheet_name="Daten")
        except NotImplementedError:
            # Fallback: mit Index schreiben (funktioniert zuverlässig)
            df.to_excel(writer, index=True, header=True, sheet_name="Daten")
    print(f"Wrote {out}")
    

if __name__ == "__main__":
    main()
