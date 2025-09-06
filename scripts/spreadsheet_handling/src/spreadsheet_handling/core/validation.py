import pandas as pd
from typing import Dict, List

def find_duplicate_ids(frames, reg) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for key, meta in reg.items():
        df = frames[meta["sheet_name"]]
        id_col = meta["id_field"]
        if not has_level0(df, id_col):
            continue
        ids = level0_series(df, id_col).astype("string")
        vc = ids.value_counts(dropna=False)
        dups = [str(v) for v, c in vc.items() if c > 1 and str(v) != "nan"]
        if dups:
            out[meta["sheet_name"]] = dups
    return out

