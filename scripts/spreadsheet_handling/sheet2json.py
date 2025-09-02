#!/usr/bin/env python3

import argparse, json, pandas as pd, math, os

def is_empty(x):
    if x is None:
        return True
    s = str(x).strip()
    # alles, was leer, NaN/None ODER "Unnamed: ..." ist, als leer behandeln
    return (s == "" 
            or s.lower() in ("nan", "none") 
            or s.startswith("Unnamed:"))

def set_in(d, path_segs, value):
    cur = d
    for i,seg in enumerate(path_segs):
        last = i == len(path_segs)-1
        if last:
            cur[seg] = value
        else:
            nxt = cur.get(seg)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[seg] = nxt
            cur = nxt

def main():
    ap = argparse.ArgumentParser(description="Convert spreadsheet with N header rows to nested JSON (skipping empty header cells).")
    ap.add_argument("input", help="Input spreadsheet (.xlsx, .xls) or CSV")
    ap.add_argument("-o","--output", default="out.json", help="Output JSON file")
    ap.add_argument("--levels", type=int, required=True, help="Number of header rows (top rows) that define the hierarchy")
    ap.add_argument("--csv-delim", default=";", help="CSV delimiter if input is .csv (default ;)")
    ap.add_argument("--drop-empty-cols", action="store_true", help="Drop columns with all-empty header segments")
    args = ap.parse_args()

    path = args.input
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(path, header=list(range(args.levels)), delimiter=args.csv_delim, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(path, header=list(range(args.levels)), dtype=str)
        df = df.where(pd.notna(df), None)
    
    paths = []
    drop_cols = []
    for idx, col in enumerate(df.columns):
        segs = [str(s) for s in col if not is_empty(s)]
        if not segs:
            drop_cols.append(idx)
            paths.append(None)
        else:
            paths.append(".".join(segs))
    
    if drop_cols:
        keep = [i for i,p in enumerate(paths) if p is not None]
        df = df.iloc[:, keep]
        paths = [paths[i] for i in keep]

    
    out = []
    for _, row in df.iterrows():
        obj = {}
        for p, v in zip(paths, row.values.tolist()):
            if v is None:
                continue
            if isinstance(v, str):
                v = v.strip()
                if v == "":
                    continue
            # Pfad setzen
            segs = p.split(".")
            set_in(obj, segs, v)
        if obj:                 # <- nur nicht-leere Objekte übernehmen
            out.append(obj)
    
    res = out if len(out)>1 else (out[0] if out else {})
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"Wrote {args.output}")

if __name__ == "__main__":
    main()
