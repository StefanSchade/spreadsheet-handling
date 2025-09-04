from __future__ import annotations
import pandas as pd
from .base import BackendBase


class CSVBackend(BackendBase):
    """
    Sehr einfache CSV-Implementierung:
    - Header mit N Ebenen werden als N Zeilen geschrieben.
    - Daten folgen ab Zeile N+1.
    - Keine Merged Cells, keine Formatierung.
    - UTF-8 ohne BOM.
    """

    def write(self, df: pd.DataFrame, path: str, sheet_name: str = "Daten") -> None:
        if not isinstance(df.columns, pd.MultiIndex):
            # in ein 1-level MultiIndex heben, damit Logik konsistent ist
            df = df.copy()
            df.columns = pd.MultiIndex.from_arrays([df.columns], names=[None])

        # Header-Zeilen vorbereiten
        header_rows = []
        for lvl in range(df.columns.nlevels):
            header_rows.append(
                [str(col[lvl]) if col[lvl] is not None else "" for col in df.columns]
            )

        # DataFrame-Zeilen als Strings
        body_rows = df.astype(object).where(pd.notnull(df), "").values.tolist()

        # Schreiben
        with open(path, "w", encoding="utf-8", newline="") as f:
            for row in header_rows:
                f.write(",".join(_escape_csv_cell(v) for v in row) + "\n")
            for row in body_rows:
                f.write(",".join(_escape_csv_cell(v) for v in row) + "\n")

    def read(self, path: str, header_levels: int, sheet_name: str = "Daten") -> pd.DataFrame:
        # Erstmal roh lesen
        raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False, na_values=[])
        if header_levels <= 0:
            # kein Header → einfache Spalten
            df = raw
            df.columns = [f"col{i}" for i in range(len(df.columns))]
            return df

        # MultiIndex-Spalten aus den oberen header_levels Zeilen bauen
        header_part = raw.iloc[:header_levels, :]
        body_part = raw.iloc[header_levels:, :]

        tuples = list(zip(*[header_part.iloc[i].tolist() for i in range(header_levels)]))
        # Leere Headerzellen zu "" normalisieren (wie bei Excel-Readern),
        # später in unflatten.py werden "leere" Labels ohnehin gefiltert.
        clean_tuples = tuple(tuple(x if x != "nan" else "" for x in t) for t in tuples)

        columns = pd.MultiIndex.from_tuples(clean_tuples)
        df = pd.DataFrame(body_part.values, columns=columns)
        return df


def _escape_csv_cell(v) -> str:
    s = "" if v is None else str(v)
    # rudimentäres Escaping: Zellen mit Komma, Quote oder Newline quoten
    if any(ch in s for ch in [",", '"', "\n", "\r"]):
        s = '"' + s.replace('"', '""') + '"'
    return s
