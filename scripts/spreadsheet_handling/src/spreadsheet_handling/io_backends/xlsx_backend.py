from __future__ import annotations
from pathlib import Path
import pandas as pd
import xlsxwriter
from .base import BackendBase, BackendOptions

class ExcelBackend(BackendBase):
    def write(self, df: pd.DataFrame, path: str, sheet_name: str = "Daten") -> None:
        levels = df.columns.nlevels if isinstance(df.columns, pd.MultiIndex) else 1
        tuples = (
            list(df.columns)
            if isinstance(df.columns, pd.MultiIndex)
            else [(c,) for c in df.columns]
        )

        wb = xlsxwriter.Workbook(path)
        ws = wb.add_worksheet(sheet_name)
        fmt_h = wb.add_format({"bold": True, "valign": "bottom"})
        fmt_c = wb.add_format({})

        for lvl in range(levels):
            for col, tup in enumerate(tuples):
                ws.write(lvl, col, "" if tup[lvl] is None else str(tup[lvl]), fmt_h)

        start_row = levels
        for r, row in enumerate(df.values.tolist(), start=start_row):
            for c, val in enumerate(row):
                ws.write(r, c, "" if val is None else val, fmt_c)

        ws.freeze_panes(start_row, 0)
        wb.close()

    def read(
        self,
        path: str,
        header_levels: int,
        sheet_name: str | None = None,
        options: BackendOptions | None = None,   # <- neu, optional
    ) -> pd.DataFrame:
        hdr = list(range(header_levels)) if header_levels and header_levels > 0 else 0
        df = pd.read_excel(
            path,
            sheet_name=sheet_name,
            header=hdr,
            dtype=str,
            engine="openpyxl",
        )
        # Einheitlich: leere Zellen als "" statt NaN
        df = df.where(pd.notnull(df), "")
        return df
    

        # Wir schreiben mit *einer* Headerzeile -> hier mit header=0 lesen
        df = pd.read_excel(path, header=0, sheet_name=sheet_name or 0)
        # in MultiIndex mit 'header_levels' Ebenen heben
        tuples = [(c,) + ("",) * (header_levels - 1) for c in list(df.columns)]
        df = df.copy()
        df.columns = pd.MultiIndex.from_tuples(tuples)
        return df

    # Neu: echte Multi-Sheet-Implementierung
    def read_multi(
        self,
        path: str,
        header_levels: int,
        options: BackendOptions | None = None,
    ) -> dict[str, pd.DataFrame]:
        # alle Sheets lesen (flattened Header) und MI wiederherstellen
        sheets = pd.read_excel(path, sheet_name=None, header=0)
        out: dict[str, pd.DataFrame] = {}
        for name, df in sheets.items():
            tuples = [(c,) + ("",) * (header_levels - 1) for c in list(df.columns)]
            df = df.copy()
            df.columns = pd.MultiIndex.from_tuples(tuples)
            out[name] = df
        return out
