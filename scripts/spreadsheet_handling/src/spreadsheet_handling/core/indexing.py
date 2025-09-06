from __future__ import annotations

from typing import Iterable
import pandas as pd


def has_level0(df: pd.DataFrame, name: str) -> bool:
    """
    Prüft, ob eine Spalte 'name' auf Level-0 existiert (sowohl bei
    Single-Index als auch MultiIndex Columns).
    """
    cols = df.columns
    if isinstance(cols, pd.MultiIndex):
        # schneller Membership-Check nur auf Level-0
        lvl0: Iterable[str] = cols.get_level_values(0)
        return name in set(lvl0)
    return name in cols


def level0_series(df: pd.DataFrame, name: str) -> pd.Series:
    """
    Liefert die Spalte 'name' als Series aus Level-0.
    - Bei Single-Index Columns: df[name]
    - Bei MultiIndex Columns: xs(name, level=0), robust auf Serienform gebracht
      (falls ein DataFrame zurückkommt, wird eine eindeutige/erste Spalte gewählt).
    Raises:
        KeyError, wenn 'name' auf Level-0 nicht existiert.
    """
    cols = df.columns
    if isinstance(cols, pd.MultiIndex):
        lvl0 = cols.get_level_values(0)
        if name not in set(lvl0):
            raise KeyError(name)

        sub = df.xs(name, axis=1, level=0)  # -> Series ODER DataFrame (Restlevel)
        if isinstance(sub, pd.Series):
            return sub

        # DataFrame: versuche eine eindeutige Spalte herzuleiten
        if sub.shape[1] == 1:
            return sub.iloc[:, 0]

        # Heuristik: nimm die Spalte, deren Unterlevels "leer" sind ("" oder NaN)
        try:
            candidates = []
            for i, col in enumerate(sub.columns):
                if isinstance(col, tuple):
                    if all((x == "" or pd.isna(x)) for x in col[1:]):
                        candidates.append(i)
                else:
                    # Falls sub.columns kein Tuple ist, sofort als Kandidat werten
                    candidates.append(i)
            if len(candidates) == 1:
                return sub.iloc[:, candidates[0]]
        except Exception:
            pass

        # Fallback: nimm die erste Spalte stabil – ändert keine bisherigen Tests
        return sub.iloc[:, 0]

    # Single-Index Columns
    if name not in cols:
        raise KeyError(name)
    return df[name]

