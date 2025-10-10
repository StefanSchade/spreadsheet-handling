from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.worksheet.datavalidation import DataValidation


# Keep the base import so existing imports/typing remain valid.
from .base import BackendBase, BackendOptions


# ======================================================================================
# Styling helpers
# ======================================================================================

def _decorate_workbook(
        workbook_path: Path,
        *,
        auto_filter: bool = True,
        header_fill_rgb: str = "DDDDDD",
        freeze_header: bool = False,
) -> None:
    """
    Post-process a written XLSX file:
    - apply AutoFilter across the used range
    - color header row (row 1) with a light gray fill & bold font
    - optionally freeze the first row (pane below header)
    """
    wb = load_workbook(workbook_path)

    header_fill = PatternFill("solid", fgColor=header_fill_rgb)
    header_font = Font(bold=True)

    for ws in wb.worksheets:
        # AutoFilter across used range
        if auto_filter and ws.max_row and ws.max_column:
            ws.auto_filter.ref = ws.dimensions  # e.g. "A1:D100"

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

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl import load_workbook

def _apply_xlsx_validations(xlsx_path: Path, frames: dict[str, pd.DataFrame]) -> None:
    """
    Reads frames.meta["constraints"] (your neutral schema) and applies
    Excel data validations to the written workbook.
    MVP: supports rule.type == "in_list" on a named column.
    """
    meta = getattr(frames, "meta", {}) or {}
    constraints = meta.get("constraints") or []
    if not constraints:
        return

    wb = load_workbook(xlsx_path)
    for c in constraints:
        rule = (c or {}).get("rule") or {}
        if rule.get("type") != "in_list":
            continue  # only handle in_list in MVP

        sheet = c.get("sheet")
        col_name = c.get("column")
        if not sheet or not col_name or sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]

        col_ix = _find_col_index_by_header(ws, col_name)  # 1-based
        if not col_ix:
            continue

        start_row = 2                      # assume row 1 is header
        end_row = max(ws.max_row or 1, 2)  # at least two rows
        cell_range = f"{get_column_letter(col_ix)}{start_row}:{get_column_letter(col_ix)}{end_row}"

        values = list(rule.get("values") or [])
        if not values:
            continue

        dv = DataValidation(type="list", formula1=f'"{",".join(map(str, values))}"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(cell_range)

    wb.save(xlsx_path)

def _find_col_index_by_header(ws: Worksheet, header: str) -> int | None:
    """
    Map header-text in row 1 to 1-based column index. Strict string match.
    """
    for j, cell in enumerate(ws[1], start=1):
        if str(cell.value) == str(header):
            return j
    return None



def _flatten_header_to_level0(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure we write a single header row:
    - if columns is a MultiIndex, take level 0
    - otherwise keep as-is
    """
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [t[0] for t in df.columns.to_list()]
    return df


# ======================================================================================
# Excel backend (multi-sheet only)
# ======================================================================================

class ExcelBackend(BackendBase):
    """
    XLSX adapter backed by pandas + openpyxl.

    Public API (used by our router/tests):
      - write_multi(frames, path, options=None)
      - read_multi(path, header_levels, options=None)
    """

    def write_multi(
            self,
            frames: Dict[str, pd.DataFrame],
            path: str,
            options: BackendOptions | None = None,
    ) -> None:
        """
        Write multiple DataFrames to an XLSX:
        - one sheet per dict key
        - flatten MultiIndex headers to level 0 (single header row)
        - apply header styling (autofilter + gray + bold), optionally freeze header
        """
        out = Path(path).with_suffix(".xlsx")
        out.parent.mkdir(parents=True, exist_ok=True)

        with pd.ExcelWriter(out, engine="openpyxl") as xw:
            for sheet_name, df in frames.items():
                sheet = (sheet_name or "Sheet")[:31]  # Excel sheet name limit
                df_out = _flatten_header_to_level0(df)
                df_out.to_excel(xw, sheet_name=sheet, index=False)

        # If you later extend BackendOptions with excel-related knobs,
        # you can thread them here. For now use reasonable defaults:
        _decorate_workbook(
            out,
            auto_filter=True,
            header_fill_rgb="DDDDDD",
            freeze_header=False,
        )

        try:
            _apply_xlsx_validations(Path(out), frames)   # <-- add this line
        except Exception:
            # keep robust; don't break writing if validations fail
            pass


    def read_multi(
            self,
            path: str,
            header_levels: int,
            options: BackendOptions | None = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Read all sheets assuming a single header row (header=0).
        If header_levels > 1, lift columns to a MultiIndex (level-0 data,
        remaining levels empty strings).
        """
        p = Path(path)
        sheets = pd.read_excel(
            p, sheet_name=None, header=0, engine="openpyxl", dtype=str
        )
        out: Dict[str, pd.DataFrame] = {}
        levels = header_levels if (header_levels and header_levels > 1) else 1

        for name, df in sheets.items():
            df = df.where(pd.notnull(df), "")  # normalize NaNs to empty strings
            if not isinstance(df.columns, pd.MultiIndex) and levels > 1:
                tuples = [(c,) + ("",) * (levels - 1) for c in list(df.columns)]
                df = df.copy()
                df.columns = pd.MultiIndex.from_tuples(tuples)
            out[name] = df

        return out

# ------------------------------------------------------------------------------
# Legacy/test convenience shim
# ------------------------------------------------------------------------------

def write_xlsx(
        path: str,
        frames: Dict[str, pd.DataFrame],
        meta: Any,  # kept for signature compatibility; not used here
        ctx: Any,   # expected to hold ctx.app.excel.{auto_filter, header_fill_rgb, freeze_header}
) -> None:
    """
    Test-facing convenience used by unit tests:
    - writes XLSX with one sheet per frame (flattening header to level 0)
    - applies AutoFilter + gray/bold header
    - honors ctx.app.excel options if present
    """
    out = Path(path).with_suffix(".xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1) write via pandas (single header row)
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        for sheet_name, df in frames.items():
            sheet = (sheet_name or "Sheet")[:31]
            df_out = _flatten_header_to_level0(df)
            df_out.to_excel(xw, sheet_name=sheet, index=False)

    # 2) style according to ctx
    excel_opts = getattr(getattr(ctx, "app", None), "excel", None)
    _decorate_workbook(
        out,
        auto_filter=getattr(excel_opts, "auto_filter", True) if excel_opts else True,
        header_fill_rgb=getattr(excel_opts, "header_fill_rgb", "DDDDDD") if excel_opts else "DDDDDD",
        freeze_header=getattr(excel_opts, "freeze_header", False) if excel_opts else False,
    )


# ======================================================================================
# Test-/router-facing convenience (module-level) API
# ======================================================================================

# src/spreadsheet_handling/io_backends/xlsx_backend.py
from typing import Dict, Any
import pandas as pd
from .base import BackendOptions
from .xlsx_backend import ExcelBackend  # falls die Klasse hier liegt; sonst anpassen

def _flatten_cols_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure single-level string headers for Excel output."""
    if not isinstance(df.columns, pd.MultiIndex):
        # already flat; also guard against tuple-like strings
        df.columns = [str(c) for c in df.columns]
        return df

    def first_nonempty(tup) -> str:
        for x in tup:
            s = str(x)
            if s:
                return s
        return ""

    flat = [first_nonempty(t) for t in df.columns.tolist()]
    new_df = df.copy()
    new_df.columns = flat
    return new_df

def save_xlsx(
        frames: Dict[str, pd.DataFrame],
        path: str,
        options: BackendOptions | None = None
) -> None:
    """Router-facing saver that guarantees flat string headers."""
    sanitized: Dict[str, pd.DataFrame] = {}
    for name, df in frames.items():
        sanitized[name] = _flatten_cols_for_excel(df)
    ExcelBackend().write_multi(sanitized, path, options=options)

def load_xlsx(
        path: str,
        options: BackendOptions | None = None   # <-- NEU
) -> dict[str, pd.DataFrame]:
    """
    Router-facing reader: read all sheets, assume single header row.
    (Lifts to MultiIndex of length 1 → effectively stays flat.)
    """
    return ExcelBackend().read_multi(path, header_levels=1, options=options)


__all__ = [
    "ExcelBackend",
    "save_xlsx",
    "load_xlsx",
]

# vaildation feature

# add at top if not present
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.worksheet.datavalidation import DataValidation

def write_multi(frames, path: str, options: dict | None = None) -> None:
    # ... existing writing logic that creates wb + sheets and writes data ...
    wb = _create_workbook_from_frames(frames)  # <- your existing function/logic
    _apply_xlsx_presentation_hints(wb, frames)
    wb.save(path)

def _apply_xlsx_presentation_hints(wb, frames) -> None:
    meta = getattr(frames, "meta", {}) or {}
    pres = (meta.get("presentation") or {}).get("xlsx") or {}

    # 1) if user already provided explicit xlsx validations, apply them
    _apply_validations_from_hints(wb, pres.get("validations") or [])

    # 2) additionally: synthesize validations from generic constraints (in_list only)
    _constraints_to_validations_and_apply(wb, frames, meta.get("constraints") or [])

def _apply_validations_from_hints(wb, validations: list[dict]) -> None:
    for v in validations:
        sheet = wb[v["sheet"]]
        dv = _make_list_validation(v)
        sheet.add_data_validation(dv)
        dv.add(v["range"])

def _constraints_to_validations_and_apply(wb, frames, constraints: list[dict]) -> None:
    # MVP: only in_list on a column -> convert to a range covering all data rows
    for c in constraints:
        rule = c.get("rule") or {}
        if rule.get("type") != "in_list":
            continue  # ignore other types for now

        sheet_name = c["sheet"]
        ws = wb[sheet_name]
        col_letter = _resolve_column_letter(frames, sheet_name, c.get("column"))
        if not col_letter:
            continue

        start_row = 2  # assuming row 1 is header
        end_row = _infer_last_row(ws)
        cell_range = f"{col_letter}{start_row}:{col_letter}{end_row}"
        v = {
            "sheet": sheet_name,
            "range": cell_range,
            "values": list(rule.get("values") or []),
            "allow_blank": True,
        }
        dv = _make_list_validation(v)
        ws.add_data_validation(dv)
        dv.add(cell_range)

def _make_list_validation(v: dict) -> DataValidation:
    # values -> "A,B,C" literal list; prefer source_range if provided
    if v.get("source_range"):
        dv = DataValidation(type="list", formula1=f'={v["source_range"]}',
                            allow_blank=bool(v.get("allow_blank", True)))
    else:
        literal = ",".join(map(str, v.get("values") or []))
        dv = DataValidation(type="list", formula1=f'"{literal}"',
                            allow_blank=bool(v.get("allow_blank", True)))
    return dv

def _infer_last_row(ws: Worksheet) -> int:
    # robust end row (openpyxl sometimes leaves gaps); fallback to max used row
    return max(ws.max_row or 1, 2)

def _resolve_column_letter(frames, sheet: str, column_name: str | None) -> str | None:
    """
    Map a logical column name to an Excel column letter using the frame's current header.
    Assumes row 1 contains headers that match DataFrame columns.
    """
    if not column_name:
        return None
    # obtain the column index from frames (you likely have frames.sheets[sheet] as a list of dicts or a df)
    df = _as_dataframe(frames, sheet)  # implement according to your frames structure
    if column_name not in list(df.columns):
        return None
    idx = list(df.columns).index(column_name)  # 0-based
    return _number_to_col(idx + 1)  # 1-based

def _number_to_col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n-1, 26)
        s = chr(65 + r) + s
    return s
