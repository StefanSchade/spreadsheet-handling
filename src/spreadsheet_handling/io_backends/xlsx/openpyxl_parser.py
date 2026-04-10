from __future__ import annotations

import ast
import json
from pathlib import Path
import re
from typing import Any

import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.worksheet.worksheet import Worksheet

from spreadsheet_handling.rendering.ir import (
    DataValidationSpec,
    NamedRange,
    SheetIR,
    TableBlock,
    WorkbookIR,
)


def parse_workbook(path: str | Path) -> WorkbookIR:
    """
    Parse an XLSX workbook into ``WorkbookIR`` via openpyxl.

    Discovery priority for table structure:
      1. Embedded hidden `_meta` payload
      2. Explicit anchors passed by a future caller extension
      3. Heuristic fallback from sheet contents
    """
    wb = openpyxl.load_workbook(str(path), data_only=True)
    try:
        ir = WorkbookIR()

        embedded_meta = _read_meta_sheet(wb)

        for ws_name in wb.sheetnames:
            ws = wb[ws_name]
            if ws.sheet_state == "hidden":
                ir.hidden_sheets[ws_name] = _parse_hidden_sheet(ws)
                continue

            sheet_meta_hints = (embedded_meta.get("sheets") or {}).get(ws_name, {})
            ir.sheets[ws_name] = _parse_visible_sheet(
                ws,
                sheet_name=ws_name,
                anchors=None,
                meta_hints=sheet_meta_hints,
                stop_on_empty_row=True,
                stop_on_empty_col=False,
            )

        _extract_named_ranges(wb, ir)
        return ir
    finally:
        wb.close()


def _read_meta_sheet(wb: openpyxl.Workbook) -> dict[str, Any]:
    """Read the hidden `_meta` sheet if present and return a dict."""
    if "_meta" not in wb.sheetnames:
        return {}

    ws = wb["_meta"]
    kv: dict[str, str] = {}
    for row in ws.iter_rows(min_col=1, max_col=2, values_only=True):
        key = row[0]
        val = row[1] if len(row) > 1 else ""
        if key is not None:
            kv[str(key)] = str(val) if val is not None else ""

    blob_str = kv.get("workbook_meta_blob", "")
    if blob_str:
        try:
            return dict(json.loads(str(blob_str)))
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            result = ast.literal_eval(blob_str)
            if isinstance(result, dict):
                return result
        except (ValueError, SyntaxError):
            pass

    return kv


def _parse_hidden_sheet(ws: Worksheet) -> SheetIR:
    """Parse a hidden sheet (for example `_meta`) into a ``SheetIR``."""
    sh = SheetIR(name=ws.title)
    sh.meta["_hidden"] = True
    for row in ws.iter_rows(min_col=1, max_col=2, values_only=True):
        key = row[0]
        val = row[1] if len(row) > 1 else ""
        if key is not None:
            sh.meta[str(key)] = str(val) if val is not None else ""
    return sh


def _parse_visible_sheet(
    ws: Worksheet,
    *,
    sheet_name: str,
    anchors: list[tuple[int, int]] | None,
    meta_hints: dict[str, Any],
    stop_on_empty_row: bool,
    stop_on_empty_col: bool,
) -> SheetIR:
    """Parse a visible worksheet into ``SheetIR`` with one or more ``TableBlock`` values."""
    sh = SheetIR(name=sheet_name)

    options = {}
    for key in ("freeze_header", "auto_filter", "header_fill_rgb", "helper_prefix"):
        if key in meta_hints:
            options[key] = meta_hints[key]
    if options:
        sh.meta["options"] = options

    table_starts = anchors or [(1, 1)]
    for top, left in table_starts:
        sh.tables.append(
            _parse_table_block(
                ws,
                frame_name=sheet_name,
                top=top,
                left=left,
                stop_on_empty_row=stop_on_empty_row,
                stop_on_empty_col=stop_on_empty_col,
            )
        )

    header_merges = _extract_header_merges(ws, sh.tables)
    if header_merges:
        sh.meta["__header_merges"] = header_merges

    for tbl in sh.tables:
        grid = _extract_header_grid(ws, tbl)
        if grid and tbl.header_rows > 1:
            sh.meta["__header_grid"] = grid

    sh.validations = _extract_validations(ws)

    if ws.freeze_panes:
        _extract_freeze(ws, sh)

    if ws.auto_filter and ws.auto_filter.ref:
        sh.meta["__autofilter_ref"] = ws.auto_filter.ref

    return sh


def _parse_table_block(
    ws: Worksheet,
    *,
    frame_name: str,
    top: int,
    left: int,
    stop_on_empty_row: bool,
    stop_on_empty_col: bool,
) -> TableBlock:
    """Discover a single table starting at ``(top, left)``."""
    header_rows = _detect_header_rows(ws, top, left)
    n_cols = _find_col_extent(ws, top, left, stop_on_empty_col)
    data_start_row = top + header_rows
    n_data_rows = _find_row_extent(ws, data_start_row, left, n_cols, stop_on_empty_row)
    n_rows = header_rows + n_data_rows

    headers: list[str] = []
    leaf_row = top + header_rows - 1
    for c in range(left, left + n_cols):
        val = _cell_value(ws, leaf_row, c)
        headers.append(str(val) if val else "")

    if header_rows > 1:
        flat_headers = []
        for c in range(left, left + n_cols):
            parts = []
            for r in range(top, top + header_rows):
                val = _cell_value(ws, r, c)
                parts.append(str(val) if val else "")
            flat_headers.append(" / ".join(p for p in parts if p))
        headers = flat_headers

    header_map = {h: idx + 1 for idx, h in enumerate(headers)}

    data: list[list[Any]] = []
    for r in range(data_start_row, data_start_row + n_data_rows):
        row_vals: list[Any] = []
        for c in range(left, left + n_cols):
            val = ws.cell(row=r, column=c).value
            row_vals.append(str(val) if val is not None else "")
        data.append(row_vals)

    return TableBlock(
        frame_name=frame_name,
        top=top,
        left=left,
        header_rows=header_rows,
        header_cols=1,
        n_rows=n_rows,
        n_cols=n_cols,
        headers=headers,
        header_map=header_map,
        data=data,
    )


def _cell_value(ws: Worksheet, row: int, col: int) -> Any:
    """Get a cell value, resolving merged cells to their master value."""
    cell = ws.cell(row=row, column=col)
    if isinstance(cell, MergedCell):
        for mr in ws.merged_cells.ranges:
            if (row, col) in [
                (r, c)
                for r in range(mr.min_row, mr.max_row + 1)
                for c in range(mr.min_col, mr.max_col + 1)
            ]:
                return ws.cell(row=mr.min_row, column=mr.min_col).value
        return None
    return cell.value


def _detect_header_rows(ws: Worksheet, top: int, left: int) -> int:
    """Detect header depth by examining merge regions near the table anchor."""
    max_header_row = top
    has_horizontal_merge_at_top = False

    for mr in ws.merged_cells.ranges:
        if mr.min_row < top or mr.min_col < left:
            continue
        if mr.max_row > mr.min_row and mr.min_row >= top and mr.max_row > max_header_row:
            max_header_row = mr.max_row
        if mr.min_row == top and mr.max_col > mr.min_col and mr.min_row == mr.max_row:
            has_horizontal_merge_at_top = True

    if max_header_row > top:
        return min(max_header_row - top + 1, 10)
    if has_horizontal_merge_at_top:
        return 2
    return 1


def _find_col_extent(ws: Worksheet, top: int, left: int, stop_on_empty: bool) -> int:
    """Find the number of columns by scanning the first header row."""
    n_cols = 0
    for c in range(left, left + 16384):
        val = _cell_value(ws, top, c)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            if stop_on_empty:
                break
            has_more = False
            for lookahead in range(1, 4):
                v2 = _cell_value(ws, top, c + lookahead)
                if v2 is not None and str(v2).strip():
                    has_more = True
                    break
            if not has_more:
                break
        n_cols = c - left + 1
    return max(n_cols, 1)


def _find_row_extent(
    ws: Worksheet,
    data_start_row: int,
    left: int,
    n_cols: int,
    stop_on_empty: bool,
) -> int:
    """Find the number of data rows by scanning down from the first data row."""
    n_data_rows = 0
    for r in range(data_start_row, data_start_row + 1048576):
        row_empty = True
        for c in range(left, left + n_cols):
            val = ws.cell(row=r, column=c).value
            if val is not None and str(val).strip() != "":
                row_empty = False
                break
        if row_empty:
            if stop_on_empty:
                break
            lookahead_empty = True
            for lr in range(1, 3):
                for c in range(left, left + n_cols):
                    val = ws.cell(row=r + lr, column=c).value
                    if val is not None and str(val).strip() != "":
                        lookahead_empty = False
                        break
                if not lookahead_empty:
                    break
            if lookahead_empty:
                break
        n_data_rows = r - data_start_row + 1
    return n_data_rows


def _extract_header_merges(
    ws: Worksheet,
    tables: list[TableBlock],
) -> list[tuple[int, int, int, int]]:
    """Extract merge regions within the header area of tables in relative coordinates."""
    merges: list[tuple[int, int, int, int]] = []
    for tbl in tables:
        header_bottom = tbl.top + tbl.header_rows - 1
        for mr in ws.merged_cells.ranges:
            if (
                mr.min_row >= tbl.top
                and mr.max_row <= header_bottom
                and mr.min_col >= tbl.left
                and mr.max_col <= tbl.left + tbl.n_cols - 1
            ):
                merges.append(
                    (
                        mr.min_row - tbl.top + 1,
                        mr.min_col - tbl.left + 1,
                        mr.max_row - tbl.top + 1,
                        mr.max_col - tbl.left + 1,
                    )
                )
    return merges


def _extract_header_grid(ws: Worksheet, tbl: TableBlock) -> list[list[str]]:
    """Extract the header grid as a 2D list of strings."""
    grid: list[list[str]] = []
    for r in range(tbl.top, tbl.top + tbl.header_rows):
        row_vals: list[str] = []
        for c in range(tbl.left, tbl.left + tbl.n_cols):
            val = _cell_value(ws, r, c)
            row_vals.append(str(val) if val else "")
        grid.append(row_vals)
    return grid


def _extract_validations(ws: Worksheet) -> list[DataValidationSpec]:
    """Extract list validations from the worksheet into ``DataValidationSpec`` values."""
    specs: list[DataValidationSpec] = []
    for dv in ws.data_validations.dataValidation:
        if dv.type != "list":
            continue
        formula = str(dv.formula1) if dv.formula1 else ""
        allow_empty = bool(dv.allow_blank) if dv.allow_blank is not None else True
        for cell_range in dv.sqref.ranges:
            specs.append(
                DataValidationSpec(
                    kind="list",
                    area=(
                        cell_range.min_row,
                        cell_range.min_col,
                        cell_range.max_row,
                        cell_range.max_col,
                    ),
                    formula=formula,
                    allow_empty=allow_empty,
                )
            )
    return specs


def _extract_freeze(ws: Worksheet, sh: SheetIR) -> None:
    """Parse an openpyxl freeze-pane ref such as ``A3`` into ``__freeze`` metadata."""
    fp = ws.freeze_panes
    if not fp:
        return

    from openpyxl.utils import column_index_from_string

    col_str = ""
    row_str = ""
    for ch in str(fp):
        if ch.isalpha():
            col_str += ch
        else:
            row_str += ch
    if col_str and row_str:
        sh.meta["__freeze"] = {
            "row": int(row_str),
            "col": column_index_from_string(col_str),
        }


def _extract_named_ranges(wb: openpyxl.Workbook, ir: WorkbookIR) -> None:
    """Read workbook defined names and attach them to the matching visible sheet IR."""
    from openpyxl.utils import column_index_from_string as cifs

    for _, dn in wb.defined_names.items():
        for title, coord in dn.destinations:
            if title not in ir.sheets:
                continue
            match = re.match(r"\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)", coord)
            if not match:
                continue
            c1 = cifs(match.group(1))
            r1 = int(match.group(2))
            c2 = cifs(match.group(3))
            r2 = int(match.group(4))
            ir.sheets[title].named_ranges.append(
                NamedRange(name=dn.name, sheet=title, area=(r1, c1, r2, c2))
            )


__all__ = ["parse_workbook"]
