from __future__ import annotations

from typing import Iterable
import pandas as pd


def has_level0(df: pd.DataFrame, first_level_name: str) -> bool:
    """
    Prüft, ob es auf Level-0 eine Spalte mit dem Namen 'first_level_name' gibt.
    Funktioniert für einfache und MultiIndex-Header gleichermaßen.
    """
    if isinstance(df.columns, pd.MultiIndex):
        lvl0: Iterable[str] = df.columns.get_level_values(0)
        return first_level_name in set(lvl0)
    return first_level_name in df.columns


def level0_series(df: pd.DataFrame, first_level_name: str) -> pd.Series:
    """
    Liefert eine Series für die Spalte, die auf Level-0 'first_level_name' trägt —
    unabhängig davon, ob df.columns ein MultiIndex ist.

    - Bei MultiIndex: schneidet Level-0 heraus (xs) und nimmt ggf. die erste
      Unterspalte deterministisch.
    - Bei einfachem Header: df[first_level_name]
    """
    if isinstance(df.columns, pd.MultiIndex):
        if not has_level0(df, first_level_name):
            raise KeyError(f"Spalte {first_level_name!r} nicht gefunden (Level-0).")
        sub = df.xs(first_level_name, axis=1, level=0)
        if isinstance(sub, pd.DataFrame):
            if sub.shape[1] == 0:
                raise KeyError(f"Spalte {first_level_name!r} leer (keine Unterspalten).")
            return sub.iloc[:, 0]
        return sub  # ist bereits eine Series
    # kein MultiIndex
    return df[first_level_name]

