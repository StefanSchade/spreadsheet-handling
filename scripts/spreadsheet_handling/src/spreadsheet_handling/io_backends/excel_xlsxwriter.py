from __future__ import annotations
import pandas as pd
import xlsxwriter
from .base import BackendBase

class ExcelBackend(BackendBase):
    def write(self, df: pd.DataFrame, path: str, sheet_name: str = "Daten") -> None:
        levels = df.columns.nlevels if isinstance(df.columns, pd.MultiIndex) else 1
        tuples = list(df.columns) if isinstance(df.columns, pd.MultiIndex) else [(c,) for c in df.columns]

        wb = xlsxwriter.Workbook(path)
        ws = wb.add_worksheet(sheet_name)
        fmt_h = wb.add_format({"bold": True, "valign": "bottom"})
        fmt_c = wb.add_format({})

        # Header (mehrzeilig bei MultiIndex)
        for lvl in range(levels):
            for col, tup in enumerate(tuples):
                val = "" if tup[lvl] is None else str(tup[lvl])
                ws.write(lvl, col, val, fmt_h)

        # Daten
        start_row = levels
        values = df.values.tolist()
        for r, row in enumerate(values, start=start_row):
            for c, val in enumerate(row):
                ws.write(r, c, "" if val is None else val, fmt_c)

        ws.freeze_panes(start_row, 0)
        wb.close()

    def read(self, path: str, header_levels: int, sheet_name: str | None = None) -> pd.DataFrame:
        return pd.read_excel(
            path,
            header=list(range(header_levels)),
            sheet_name=sheet_name or 0,
            dtype=str,
        )

