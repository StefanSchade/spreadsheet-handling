#!/usr/bin/env python3

import argparse, json, pandas as pd, os, xlsxwriter

def write_excel_no_index(df, out_path, sheet_name="Daten"):
    """
    Schreibt einen DataFrame mit MultiIndex-Spalten OHNE Indexspalte.
    Schreibt die Headerzeilen manuell, danach nur die Werte.
    """
    levels = df.columns.nlevels
    tuples = list(df.columns)  # Liste von Tupeln, z.B. ('kunde','adresse','strasse')

    wb  = xlsxwriter.Workbook(out_path)
    ws  = wb.add_worksheet(sheet_name)

    fmt_header = wb.add_format({"bold": True, "text_wrap": False, "align": "left", "valign": "bottom", "border": 0})
    fmt_cell   = wb.add_format({"text_wrap": False})

    # Header schreiben (levels Zeilen)
    for lvl in range(levels):
        for col, tup in enumerate(tuples):
            val = tup[lvl] if lvl < len(tup) else ""
            ws.write(lvl, col, "" if val is None else str(val), fmt_header)

    # Daten schreiben (ohne Indexspalte)
    for r, (_, row) in enumerate(df.iterrows(), start=levels):
        for c, val in enumerate(row.tolist()):
            ws.write(r, c, "" if val is None else val, fmt_cell)

    # Komfort: Freeze Panes unter dem Header
    ws.freeze_panes(levels, 0)

    # Simple Auto-Width
    col_widths = [0]*len(tuples)
    # nimm Header + Daten als Basis
    for c, tup in enumerate(tuples):
        for lvl in range(levels):
            s = str(tup[lvl]) if lvl < len(tup) and tup[lvl] is not None else ""
            col_widths[c] = max(col_widths[c], len(s))
    for r, (_, row) in enumerate(df.iterrows(), start=levels):
        for c, val in enumerate(row.tolist()):
            s = "" if val is None else str(val)
            col_widths[c] = max(col_widths[c], len(s))

    for c, w in enumerate(col_widths):
        ws.set_column(c, c, min(max(8, w + 2), 60))  # 8..60

    wb.close()


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
    
    # First-seen order, stabil über alle Ebenen
    all_cols = []
    seen = set()
    for r in flat_rows:
        for k in r.keys():  # dict() behält Einfügereihenfolge
            if k not in seen:
                seen.add(k)
                all_cols.append(k)

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
        out = out.rsplit(".", 1)[0] + ".xlsx"
    write_excel_no_index(df, out, sheet_name="Daten")
    print(f"Wrote {out}")
    

if __name__ == "__main__":
    main()
