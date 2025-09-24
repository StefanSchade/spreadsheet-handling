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

   # optional: options tolerieren
    def read(
        self,
        path: str,
        header_levels: int,
        sheet_name: str | None = None,
        options: BackendOptions | None = None,
    ) -> pd.DataFrame:
        hdr = list(range(header_levels)) if header_levels and header_levels > 0 else 0
        df = pd.read_csv(
            path,
            header=hdr,
            dtype=str,
            keep_default_na=False,
            na_values=[],
        )
        return df
    
    # Neu: Multi-Sheet aus Ordner
    def read_multi(
        self,
        path: str,
        header_levels: int,
        options: BackendOptions | None = None,
    ) -> dict[str, pd.DataFrame]:
        folder = Path(path)
        out: dict[str, pd.DataFrame] = {}
        for p in sorted(folder.glob("*.csv")):
            df = pd.read_csv(p, header=0, encoding="utf-8")
            tuples = [(c,) + ("",) * (header_levels - 1) for c in list(df.columns)]
            df = df.copy()
            df.columns = pd.MultiIndex.from_tuples(tuples)
            out[p.stem] = df
        if not out:
            raise FileNotFoundError(f"Keine *.csv in {folder} gefunden.")
        return out
