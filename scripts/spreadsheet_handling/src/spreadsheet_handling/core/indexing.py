from __future__ import annotations
import pandas as pd

def has_level0(df: pd.DataFrame, name: str) -> bool:
    cols = df.columns
    if isinstance(cols, pd.MultiIndex):
        return name in cols.get_level_values(0)
    return name in cols

def level0_series(df: pd.DataFrame, name: str) -> pd.Series:
    if isinstance(df.columns, pd.MultiIndex):
        return df.xs(name, axis=1, level=0)
    return df[name]

