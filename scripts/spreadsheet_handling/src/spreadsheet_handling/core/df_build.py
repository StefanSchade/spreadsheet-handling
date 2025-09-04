# core/df_build.py
import pandas as pd
from .paths import split_path


def build_df_from_records(records: list[dict], levels: int) -> pd.DataFrame:
    # Spalten in first-seen-order
    all_cols, seen = [], set()
    for r in records:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                all_cols.append(k)

    # MultiIndex-Tuples erzeugen
    tuples = []
    for path in all_cols:
        segs = split_path(path)
        if len(segs) >= levels:
            head = segs[: levels - 1]
            tail = ".".join(segs[levels - 1 :])
            segs = head + [tail]
        else:
            segs = segs + [""] * (levels - len(segs))
        tuples.append(tuple(segs))

    mi = pd.MultiIndex.from_tuples(tuples)
    df = pd.DataFrame([{c: r.get(c, "") for c in all_cols} for r in records])
    df.columns = mi
    return df
