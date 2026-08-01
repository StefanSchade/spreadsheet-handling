"""Spreadsheet-semantic table interpretation for the ODS read path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from spreadsheet_handling.rendering.ir import DataValidationSpec, SheetIR, TableBlock

OPTION_HINT_KEYS = (
    "freeze_header",
    "auto_filter",
    "header_fill_rgb",
    "helper_fill_rgb",
    "helper_columns",
    "helper_prefix",
    "protection",
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
    meta_hints = {key: workbook_meta[key] for key in OPTION_HINT_KEYS if key in workbook_meta}
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
    anchors: list[tuple[int, int]] | None = None,
    stop_on_empty_col: bool = False,
    exact_header_depth: int | None = None,
) -> SheetIR:
    """Interpret a visible ODS sheet into spreadsheet-neutral ``SheetIR``.

    When ``exact_header_depth`` is set (GX-4 opt-in, mirroring the GX-3a XLSX
    path), the *primary* table (the first anchor) is read in exact mode: the
    configured depth overrides merge-based detection and a lossless per-cell
    ``header_grid`` is attached. All other tables and every legacy behaviour are
    unchanged.
    """
    sheet = SheetIR(name=sheet_name)

    options = {}
    for key in OPTION_HINT_KEYS:
        if key in meta_hints:
            options[key] = meta_hints[key]
    if options:
        sheet.meta["options"] = options

    table_starts = anchors or [(1, 1)]
    for index, (top, left) in enumerate(table_starts):
        sheet.tables.append(
            _parse_table_block(
                parsed,
                frame_name=sheet_name,
                top=top,
                left=left,
                stop_on_empty_col=stop_on_empty_col,
                exact_header_depth=exact_header_depth if index == 0 else None,
            )
        )

    header_merges: list[tuple[int, int, int, int]] = []
    for table_block in sheet.tables:
        header_merges.extend(_extract_header_merges(parsed, table_block))
        # Exact-mode tables are authoritative through ``tbl.header_grid`` and are
        # skipped so there is one truth per table (mirrors the XLSX read path).
        if table_block.header_grid is None and table_block.header_rows > 1:
            sheet.meta["__header_grid"] = _extract_header_grid(parsed, table_block)

    if header_merges:
        sheet.meta["__header_merges"] = header_merges

    if autofilter_ref:
        sheet.meta["__autofilter_ref"] = autofilter_ref
    sheet.validations = list(validations)
    return sheet


def _parse_table_block(
    parsed: ParsedTable,
    *,
    frame_name: str,
    top: int,
    left: int,
    stop_on_empty_col: bool,
    exact_header_depth: int | None = None,
) -> TableBlock:
    if exact_header_depth is not None:
        return _parse_exact_table_block(
            parsed,
            frame_name=frame_name,
            top=top,
            left=left,
            depth=exact_header_depth,
            stop_on_empty_col=stop_on_empty_col,
        )
    header_rows = _detect_header_rows(parsed, top, left)
    n_cols = _find_col_extent(parsed, top, left, stop_on_empty_col)
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
            [str(_grid_value(parsed, row, col) or "") for col in range(left, left + n_cols)]
        )

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


def _exact_header_cell(parsed: ParsedTable, row: int, col: int) -> str:
    """Read one header cell verbatim, resolving merged masters, blanks as ``""``."""
    value = _grid_value(parsed, row, col)
    return "" if value is None else str(value)


def _parse_exact_table_block(
    parsed: ParsedTable,
    *,
    frame_name: str,
    top: int,
    left: int,
    depth: int,
    stop_on_empty_col: bool,
) -> TableBlock:
    """GX-4 exact read: configured ``depth`` header rows, lossless ``header_grid``.

    Mirrors the accepted GX-3a XLSX exact block. Column extent is measured on the
    *leaf* header row (fully populated), never from merge geometry. Every physical
    header cell is captured verbatim (merged masters resolved, blanks kept as
    ``""``); no ``" / "`` join is done. ``headers``/``header_map`` carry the
    non-authoritative leaf row only. Cell reads go through the already-bounded
    ``ParsedTable`` grid, so ODS row/column-repeat expansion stays within the
    existing ``ParserLimits`` extent.
    """
    header_rows = depth
    leaf_row = top + header_rows - 1
    n_cols = _find_col_extent(parsed, top, left, stop_on_empty_col, scan_row=leaf_row)
    data_start_row = top + header_rows
    n_data_rows = _find_row_extent(parsed, data_start_row, left, n_cols)
    n_rows = header_rows + n_data_rows

    header_grid = tuple(
        tuple(
            _exact_header_cell(parsed, top + row_off, left + col_off)
            for col_off in range(n_cols)
        )
        for row_off in range(header_rows)
    )
    headers = list(header_grid[-1])  # leaf row, non-authoritative
    header_map = {header: idx + 1 for idx, header in enumerate(headers)}

    data: list[list[Any]] = []
    for row in range(data_start_row, data_start_row + n_data_rows):
        data.append(
            [str(_grid_value(parsed, row, col) or "") for col in range(left, left + n_cols)]
        )

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
        header_grid=header_grid,
    )


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


def _find_col_extent(
    parsed: ParsedTable,
    top: int,
    left: int,
    stop_on_empty: bool = False,
    *,
    scan_row: int | None = None,
) -> int:
    """Find the number of columns by scanning a header row.

    Legacy callers scan the first header row (``scan_row is None``). GX-4 exact
    mode scans the *leaf* header row instead, which is fully populated (row-key
    leaf label + dynamic leaf labels), so a blank upper cell above a row-key
    column cannot truncate the column count (mirrors the XLSX read path).
    """
    row = top if scan_row is None else scan_row
    n_cols = 0
    max_scan = max(parsed.max_col, left)
    for col in range(left, max_scan + 1):
        value = _grid_value(parsed, row, col)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            if stop_on_empty:
                break
            has_more = False
            for lookahead in range(1, 4):
                if col + lookahead > parsed.max_col:
                    continue
                later = _grid_value(parsed, row, col + lookahead)
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
