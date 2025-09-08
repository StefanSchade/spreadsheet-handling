from __future__ import annotations
import pandas as pd
from .base import BackendBase

def _escape_csv_cell(v) -> str:
    s = "" if v is None else str(v)
    if any(ch in s for ch in [",", '"', "\n", "\r"]):
        s = '"' + s.replace('"', '""') + '"'
    return s

class CSVBackend(BackendBase):
    """
    Einfache CSV-Implementierung:
    - Header mit N Ebenen werden als N Zeilen geschrieben.
    - Daten folgen ab Zeile N+1.
    - UTF-8 ohne BOM.
    """

    def write(self, df: pd.DataFrame, path: str, sheet_name: str = "Daten") -> None:
        if not isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = pd.MultiIndex.from_arrays([df.columns], names=[None])

        header_rows = []
        for lvl in range(df.columns.nlevels):
            header_rows.append(
                [str(col[lvl]) if col[lvl] is not None else "" for col in df.columns]
            )

        body_rows = df.astype(object).where(pd.notnull(df), "").values.tolist()

        with open(path, "w", encoding="utf-8", newline="") as f:
            for row in header_rows:
                f.write(",".join(_escape_csv_cell(v) for v in row) + "\n")
            for row in body_rows:
                f.write(",".join(_escape_csv_cell(v) for v in row) + "\n")

    def read(self, path: str, header_levels: int, sheet_name: str = "Daten") -> pd.DataFrame:
        raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False, na_values=[])
        if header_levels <= 0:
            df = raw
            df.columns = [f"col{i}" for i in range(len(df.columns))]
            return df

        header_part = raw.iloc[:header_levels, :]
        body_part = raw.iloc[header_levels:, :]

        tuples = list(zip(*[header_part.iloc[i].tolist() for i in range(header_levels)]))
        clean_tuples = tuple(tuple(x if x != "nan" else "" for x in t) for t in tuples)

        columns = pd.MultiIndex.from_tuples(clean_tuples)
        df = pd.DataFrame(body_part.values, columns=columns)
        return df

