# io_backends/excel_xlsxwriter.py
import pandas as pd
import xlsxwriter
from .base import BackendBase


class ExcelBackend(BackendBase):
    def write(self, df: pd.DataFrame, path: str, sheet_name: str = "Daten") -> None:
        # Custom-Writer: MultiHeader OHNE Indexspalte
        levels = df.columns.nlevels
        tuples = list(df.columns)
        wb = xlsxwriter.Workbook(path)
        ws = wb.add_worksheet(sheet_name)
        fmt_h = wb.add_format({"bold": True, "valign": "bottom"})
        fmt_c = wb.add_format({})
        # Header
        for lvl in range(levels):
            for col, tup in enumerate(tuples):
                ws.write(lvl, col, "" if tup[lvl] is None else str(tup[lvl]), fmt_h)
        # Daten
        for r, (_, row) in enumerate(df.iterrows(), start=levels):
            for c, val in enumerate(row.tolist()):
                ws.write(r, c, "" if val is None else val, fmt_c)
        ws.freeze_panes(levels, 0)
        wb.close()

    def read(self, path: str, header_levels: int, sheet_name: str | None = None) -> pd.DataFrame:
        return pd.read_excel(
            path,
            header=list(range(header_levels)),
            sheet_name=sheet_name or 0,
            dtype=str,
        )
