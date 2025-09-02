import pandas as pd

def is_empty_header(x: str | None) -> bool:
    if x is None: return True
    s = str(x).strip()
    return s == "" or s.lower() in ("nan","none") or s.startswith("Unnamed:")

def set_nested(d, segs, value):
    cur = d
    for i, s in enumerate(segs):
        last = i == len(segs)-1
        if last:
            cur[s] = value
        else:
            cur = cur.setdefault(s, {})

def row_to_obj(paths: list[str], values: list[str]) -> dict:
    obj = {}
    for p, v in zip(paths, values):
        if v is None: continue
        if isinstance(v, str) and v.strip() == "": continue
        segs = p.split(".")
        if segs and segs[0].startswith("_"):   # Hilfsspalten nicht zurückschreiben
            continue
        set_nested(obj, segs, v)
    return obj

def df_to_objects(df: pd.DataFrame) -> list[dict]:
    # Header-Pfade bauen, leere/Unnamed-Zellen skippen
    paths = []
    for col in df.columns:
        segs = [str(s) for s in col if not is_empty_header(s)]
        if not segs:  # komplett leerer Header -> Spalte ignorieren
            paths.append(None)
        else:
            paths.append(".".join(segs))
    # Spalten mit None droppen
    keep = [i for i, p in enumerate(paths) if p is not None]
    df2 = df.iloc[:, keep]
    paths2 = [paths[i] for i in keep]

    out = []
    for _, row in df2.iterrows():
        obj = row_to_obj(paths2, row.values.tolist())
        if obj:
            out.append(obj)
    return out

