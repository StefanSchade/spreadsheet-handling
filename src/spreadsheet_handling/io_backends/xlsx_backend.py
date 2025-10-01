from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font

from .base import BackendBase, BackendOptions


# ------------------------------
# Internal: header decorations
# ------------------------------

def _decorate_workbook(
        workbook_path: Path,
        *,
        auto_filter: bool = True,
        header_fill_rgb: str = "DDDDDD",
        freeze_header: bool = False,
) -> None:
    """Post-process an XLSX file: AutoFilter + gray bold header (+ optional freeze)."""
    wb = load_workbook(workbook_path)

    header_fill = PatternFill("solid", fgColor=header_fill_rgb)
    header_font = Font(bold=True)

    for ws in wb.worksheets:
        # AutoFilter across used range
        if auto_filter and ws.max_row and ws.max_column:
            ws.auto_filter.ref = ws.dimensions

        # Header styling (row 1)
        if ws.max_column:
            for col_idx in range(1, ws.max_column + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font

        # Freeze pane below header
        if freeze_header:
            ws.freeze_panes = "A2"

    wb.save(workbook_path)


# ------------------------------
# ExcelBackend (multi-sheet only)
# ------------------------------

class ExcelBackend(BackendBase):
    """
    XLSX adapter backed by pandas + openpyxl.

    Public API:
    - write_multi(frames, path, options)
    - read_multi(path, header_levels, options)
    """

    def write_multi(
            self,
            frames: Dict[str, pd.DataFrame],
            path: str,
            options: BackendOptions | None = None,
    ) -> None:
        """
        Write multiple DataFrames to an XLSX (one sheet per name), flattening
        MultiIndex header to level 0. Then decorate header (autofilter + gray + bold).
        """
        out = Path(path).with_suffix(".xlsx")
        out.parent.mkdir(parents=True, exist_ok=True)

        with pd.ExcelWriter(out, engine="openpyxl") as xw:
            for sheet, df in frames.items():
                df_out = df.copy()
                if isinstance(df_out.columns, pd.MultiIndex):
                    df_out.columns = [t[0] for t in df_out.columns.to_list()]
                sheet_name = (sheet or "Sheet")[:31]
                df_out.to_excel(xw, sheet_name=sheet_name, index=False)

        # Styling options: BackendOptions has no excel-specific fields, so defaults here.
        _decorate_workbook(out)

    def read_multi(
            self,
            path: str,
            header_levels: int,
            options: BackendOptions | None = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Read all sheets; assume writer produced a single header row (header=0),
        then lift to a MultiIndex of length `header_levels` if > 1.
        """
        p = Path(path)
        sheets = pd.read_excel(p, sheet_name=None, header=0, engine="openpyxl", dtype=str)
        out: Dict[str, pd.DataFrame] = {}
        levels = header_levels if (header_levels and header_levels > 1) else 1
        for name, df in sheets.items():
            df = df.where(pd.notnull(df), "")
            if not isinstance(df.columns, pd.MultiIndex) and levels > 1:
                tuples = [(c,) + ("",) * (levels - 1) for c in list(df.columns)]
                df = df.copy()
                df.columns = pd.MultiIndex.from_tuples(tuples)
            out[name] = df
        return out


# ------------------------------
# Test-facing convenience API
# ------------------------------

def write_xlsx(
        path: str,
        frames: Dict[str, pd.DataFrame],
        meta: Any,  # MetaDict (kept loose to avoid import cycles in tests)
        ctx: Any,   # Context
) -> None:
    """
    Small convenience used by unit tests:
    - writes XLSX with one sheet per frame (flattening header)
    - applies AutoFilter + gray/bold header
    - honors ctx.app.excel.{auto_filter, header_fill_rgb, freeze_header} if present
    """
    out = Path(path).with_suffix(".xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1) write via pandas
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        for sheet, df in frames.items():
            df_out = df.copy()
            if isinstance(df_out.columns, pd.MultiIndex):
                df_out.columns = [t[0] for t in df_out.columns.to_list()]
            sheet_name = (sheet or "Sheet")[:31]
            df_out.to_excel(xw, sheet_name=sheet_name, index=False)

    # 2) style according to ctx.app.excel if present
    excel_opts = getattr(getattr(ctx, "app", None), "excel", None)
    _decorate_workbook(
        out,
        auto_filter=getattr(excel_opts, "auto_filter", True) if excel_opts else True,
        header_fill_rgb=getattr(excel_opts, "header_fill_rgb", "DDDDDD") if excel_opts else "DDDDDD",
        freeze_header=getattr(excel_opts, "freeze_header", False) if excel_opts else False,
    )
