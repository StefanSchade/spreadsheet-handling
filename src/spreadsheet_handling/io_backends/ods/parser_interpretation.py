from __future__ import annotations

"""Spreadsheet-semantic table interpretation for the ODS read path."""

from dataclasses import dataclass
from typing import Any, Mapping

from spreadsheet_handling.rendering.ir import DataValidationSpec, SheetIR, TableBlock


OPTION_HINT_KEYS = (
    "freeze_header",
    "auto_filter",
    "header_fill_rgb",
    "helper_fill_rgb",
    "helper_prefix",
)


@dataclass
class ParsedTable:
    values: dict[tuple[int, int], str]
    merges: list[tuple[int, int, int, int]]
    validation_cells: dict[str, list[tuple[int, int]]]
    max_row: int
    max_col: int


def build_sheet_meta_hints(
    workbook_meta: Mapping[str, Any],
    *,
    sheet_name: str,
) -> dict[str, Any]:
    """Merge workbook defaults with sheet-local overrides for one visible sheet."""
    meta_hints = {
        key: workbook_meta[key]
        for key in OPTION_HINT_KEYS
        if key in workbook_meta
    }
    sheet_meta_hints = (workbook_meta.get("sheets") or {}).get(sheet_name, {})
    if isinstance(sheet_meta_hints, dict):
        meta_hints.update(sheet_meta_hints)
    return meta_hints


def build_visible_sheet_ir(
    parsed: ParsedTable,
    *,
    sheet_name: str,
    meta_hints: Mapping[str, Any],
    validations: list[DataValidationSpec],
    autofilter_ref: str | None,
) -> SheetIR:
    """Interpret a visible ODS sheet into spreadsheet-neutral ``SheetIR``."""
    sheet = SheetIR(name=sheet_name)

    options = {}
    for key in OPTION_HINT_KEYS:
        if key in meta_hints:
            options[key] = meta_hints[key]
    if options:
        sheet.meta["options"] = options

    top = 1
    left = 1
    header_rows = _detect_header_rows(parsed, top, left)
    n_cols = _find_col_extent(parsed, top, left)
    data_start_row = top + header_rows
    n_data_rows = _find_row_extent(parsed, data_start_row, left, n_cols)
    n_rows = header_rows + n_data_rows

    headers: list[str] = []
    leaf_row = top + header_rows - 1
    for col in range(left, left + n_cols):
        value = _grid_value(parsed, leaf_row, col)
        headers.append(str(value) if value else "")

    if header_rows > 1:
        flattened: list[str] = []
        for col in range(left, left + n_cols):
            parts = []
            for row in range(top, top + header_rows):
                value = _grid_value(parsed, row, col)
                parts.append(str(value) if value else "")
            flattened.append(" / ".join(part for part in parts if part))
        headers = flattened

    header_map = {header: idx + 1 for idx, header in enumerate(headers)}
    data: list[list[Any]] = []
    for row in range(data_start_row, data_start_row + n_data_rows):
        data.append(
            [
                str(_grid_value(parsed, row, col) or "")
                for col in range(left, left + n_cols)
            ]
        )

    table_block = TableBlock(
        frame_name=sheet_name,
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
    sheet.tables.append(table_block)

    header_merges = _extract_header_merges(parsed, table_block)
    if header_merges:
        sheet.meta["__header_merges"] = header_merges
    if table_block.header_rows > 1:
        sheet.meta["__header_grid"] = _extract_header_grid(parsed, table_block)

    if autofilter_ref:
        sheet.meta["__autofilter_ref"] = autofilter_ref
    sheet.validations = list(validations)
    return sheet


def _grid_value(parsed: ParsedTable, row: int, col: int) -> Any:
    direct = parsed.values.get((row, col))
    if direct not in (None, ""):
        return direct
    for r1, c1, r2, c2 in parsed.merges:
        if r1 <= row <= r2 and c1 <= col <= c2:
            return parsed.values.get((r1, c1), "")
    return direct or ""


def _detect_header_rows(parsed: ParsedTable, top: int, left: int) -> int:
    max_header_row = top
    has_horizontal_merge_at_top = False

    for r1, c1, r2, c2 in parsed.merges:
        if r1 < top or c1 < left:
            continue
        if r2 > r1 and r2 > max_header_row:
            max_header_row = r2
        if r1 == top and c2 > c1 and r1 == r2:
            has_horizontal_merge_at_top = True

    if max_header_row > top:
        return min(max_header_row - top + 1, 10)
    if has_horizontal_merge_at_top:
        return 2
    return 1


def _find_col_extent(parsed: ParsedTable, top: int, left: int) -> int:
    n_cols = 0
    max_scan = max(parsed.max_col, left)
    for col in range(left, max_scan + 1):
        value = _grid_value(parsed, top, col)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            has_more = False
            for lookahead in range(1, 4):
                if col + lookahead > parsed.max_col:
                    continue
                later = _grid_value(parsed, top, col + lookahead)
                if later is not None and str(later).strip():
                    has_more = True
                    break
            if not has_more:
                break
        n_cols = col - left + 1
    return max(n_cols, 1)


def _find_row_extent(parsed: ParsedTable, data_start_row: int, left: int, n_cols: int) -> int:
    n_rows = 0
    for row in range(data_start_row, parsed.max_row + 1):
        row_empty = True
        for col in range(left, left + n_cols):
            value = _grid_value(parsed, row, col)
            if value is not None and str(value).strip() != "":
                row_empty = False
                break
        if row_empty:
            lookahead_empty = True
            for lookahead in range(1, 3):
                if row + lookahead > parsed.max_row:
                    continue
                for col in range(left, left + n_cols):
                    value = _grid_value(parsed, row + lookahead, col)
                    if value is not None and str(value).strip() != "":
                        lookahead_empty = False
                        break
                if not lookahead_empty:
                    break
            if lookahead_empty:
                break
        n_rows = row - data_start_row + 1
    return n_rows


def _extract_header_merges(
    parsed: ParsedTable,
    table_block: TableBlock,
) -> list[tuple[int, int, int, int]]:
    merges: list[tuple[int, int, int, int]] = []
    header_bottom = table_block.top + table_block.header_rows - 1
    for r1, c1, r2, c2 in parsed.merges:
        if (
            r1 >= table_block.top
            and r2 <= header_bottom
            and c1 >= table_block.left
            and c2 <= table_block.left + table_block.n_cols - 1
        ):
            merges.append(
                (
                    r1 - table_block.top + 1,
                    c1 - table_block.left + 1,
                    r2 - table_block.top + 1,
                    c2 - table_block.left + 1,
                )
            )
    return merges


def _extract_header_grid(parsed: ParsedTable, table_block: TableBlock) -> list[list[str]]:
    grid: list[list[str]] = []
    for row in range(table_block.top, table_block.top + table_block.header_rows):
        grid.append(
            [
                str(_grid_value(parsed, row, col) or "")
                for col in range(table_block.left, table_block.left + table_block.n_cols)
            ]
        )
    return grid


__all__ = [
    "OPTION_HINT_KEYS",
    "ParsedTable",
    "build_sheet_meta_hints",
    "build_visible_sheet_ir",
]
