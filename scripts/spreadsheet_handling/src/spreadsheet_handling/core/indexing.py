from __future__ import annotations

from typing import Optional
import pandas as pd

import pandas as pd
from typing import Optional

def _find_tuple_col(columns: pd.Index, level0_name: str) -> Optional[tuple]:
    """
    In einem *einfachen* Index (kein MultiIndex) nach einer Tuple-Spalte suchen,
    deren erstes Element dem gesuchten Level-0-Namen entspricht.
    """
    for c in columns:
        if isinstance(c, tuple) and len(c) > 0 and c[0] == level0_name:
            return c
    return None


def has_level0(df: pd.DataFrame, first_level_name: str) -> bool:
    if isinstance(df.columns, pd.MultiIndex):
        return first_level_name in set(df.columns.get_level_values(0))
    # exakter String-Treffer?
    if first_level_name in df.columns:
        return True
    # Fallback: Tuple-Spalten im Plain-Index
    return _find_tuple_col(df.columns, first_level_name) is not None


def level0_series(df: pd.DataFrame, first_level_name: str) -> pd.Series:
    if isinstance(df.columns, pd.MultiIndex):
        # 1) Versuche explizit eine Spalte, deren Level-0 passt
        for col in df.columns:
            if isinstance(col, tuple) and len(col) > 0 and col[0] == first_level_name:
                return df[col]
        # 2) Fallback: xs über Level 0 (liefert Series oder DataFrame)
        sub = df.xs(first_level_name, level=0, axis=1)
        return sub.iloc[:, 0] if isinstance(sub, pd.DataFrame) else sub

    # Plain Index:
    if first_level_name in df.columns:
        return df[first_level_name]
    tup = _find_tuple_col(df.columns, first_level_name)
    if tup is not None:
        return df[tup]
    raise KeyError(first_level_name)

