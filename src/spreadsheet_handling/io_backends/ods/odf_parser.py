from __future__ import annotations

import ast
from collections import defaultdict
import csv
import json
from pathlib import Path
import re
from typing import Any

from odf.element import Element
from odf.namespaces import FONS, OFFICENS, STYLENS, TABLENS, TEXTNS
from odf.opendocument import load
from odf.style import (
    ParagraphProperties,
    Style,
    TableCellProperties,
    TableColumnProperties,
    TableProperties,
)
from odf.table import (
    ContentValidation as OdfContentValidation,
    CoveredTableCell,
    DatabaseRange,
    NamedRange as OdfNamedRange,
    Table,
    TableCell,
    TableColumn,
    TableRow,
)
from odf.text import S

from spreadsheet_handling.io_backends.presentation_meta import (
    apply_cell_addressed_presentation_meta,
)
from spreadsheet_handling.io_backends.ods.parser_interpretation import (
    ParsedTable,
    build_sheet_meta_hints,
    build_visible_sheet_ir,
)
from spreadsheet_handling.io_backends.parser_limits import (
    DEFAULT_LIMITS,
    ParserLimits,
)
from spreadsheet_handling.rendering.ir import (
    DataValidationSpec,
    NamedRange,
    SheetIR,
    WorkbookIR,
)
from spreadsheet_handling.core.formulas import ListLiteralFormulaSpec


def _column_index(letters: str) -> int:
    value = 0
    for char in letters:
        value = value * 26 + (ord(char.upper()) - ord("A") + 1)
    return value


def _column_letters(index: int) -> str:
    letters = ""
    n = index
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters or "A"


def _cell_text(node: Element) -> str:
    parts: list[str] = []
    space_name = S().qname

    for fragment in node.childNodes:
        if isinstance(fragment, Element):
            if fragment.qname == space_name:
                spaces = int(fragment.attributes.get((TEXTNS, "c"), 1))
                parts.append(" " * spaces)
            else:
                parts.append(_cell_text(fragment))
        else:
            parts.append(str(fragment).strip("\n"))
    return "".join(parts)


def _cell_value(cell: Element) -> str:
    text = _cell_text(cell)
    if text:
        return text

    value_type = cell.attributes.get((OFFICENS, "value-type"))
    if value_type == "string":
        return str(cell.attributes.get((OFFICENS, "string-value"), ""))
    if value_type == "float":
        return str(cell.attributes.get((OFFICENS, "value"), ""))
    if value_type == "boolean":
        value = str(cell.attributes.get((OFFICENS, "boolean-value"), "false"))
        return "TRUE" if value == "true" else "FALSE"
    if value_type == "date":
        return str(cell.attributes.get((OFFICENS, "date-value"), ""))
    if value_type == "time":
        return str(cell.attributes.get((OFFICENS, "time-value"), ""))
    return ""


_CM_RE = re.compile(r"([\d.]+)\s*(cm|mm|in|pt|px)")
_CM_PER_UNIT = {"cm": 1.0, "mm": 0.1, "in": 2.54, "pt": 2.54 / 72, "px": 2.54 / 96}
_EXCEL_CHARS_PER_CM = 1.0 / 0.254  # 1 Excel char unit ≈ 0.254 cm


def _ods_length_to_cm(value: str) -> float | None:
    m = _CM_RE.search(str(value))
    if not m:
        return None
    try:
        amount = float(m.group(1))
        return amount * _CM_PER_UNIT.get(m.group(2), 1.0)
    except (TypeError, ValueError):
        return None


def _ods_cm_to_excel_chars(cm: float) -> float:
    return round(cm * _EXCEL_CHARS_PER_CM, 2)


def _ods_rotation_to_xlsx(ods_rotation: int) -> int:
    """Convert ODS CCW rotation (0-360) to XLSX textRotation convention (0-180).

    XLSX 0-90: CCW degrees. XLSX 91-180: CW degrees stored as 90 + CW_angle.
    ODS 90 -> XLSX 90; ODS 270 -> XLSX 180 (CW 90 degrees).
    """
    r = ods_rotation % 360
    if r == 0:
        return 0
    if r <= 90:
        return r
    # ODS 91-359: clockwise component; XLSX stores CW as 90 + CW_angle
    cw = (360 - r) % 360
    return min(90 + cw, 180)


def _build_column_style_map(doc) -> dict[str, str]:
    """Return mapping {style_name -> column-width CSS string} for table-column styles."""
    result: dict[str, str] = {}
    col_props_name = TableColumnProperties().qname
    for style in doc.getElementsByType(Style):
        if style.attributes.get((STYLENS, "family")) != "table-column":
            continue
        name = style.attributes.get((STYLENS, "name"))
        if not name:
            continue
        for child in style.childNodes:
            if not isinstance(child, Element) or child.qname != col_props_name:
                continue
            width = child.attributes.get(
                (STYLENS, "column-width"),
                child.attributes.get((TABLENS, "column-width"), ""),
            )
            if width:
                result[str(name)] = str(width)
    return result


def _extract_ods_column_widths(
    table: Element,
    col_style_map: dict[str, str],
    *,
    max_col: int,
    limits: ParserLimits = DEFAULT_LIMITS,
) -> dict[str, dict] | None:
    """Return {col_letter: {width, source}} for explicitly styled table columns.

    Iteration is clipped to ``max_col`` (the parsed content extent) so that
    sheet-wide LibreOffice column-width fillers (a styled table-column with a
    huge ``number-columns-repeated``) do not produce one metadata entry per
    filler column. ``limits`` is honoured on a per-axis basis as
    defense-in-depth against inputs that still declare implausible repeats
    within the content extent.
    """
    if max_col <= 0:
        return None
    result: dict[str, dict] = {}
    table_col_name = TableColumn().qname
    table_name = str(table.attributes.get((TABLENS, "name"), "<unnamed>"))
    context = f"ODS sheet '{table_name}' column widths"
    col_index = 1
    for child in table.childNodes:
        if not isinstance(child, Element) or child.qname != table_col_name:
            continue
        if col_index > max_col:
            break
        repeat = int(child.attributes.get((TABLENS, "number-columns-repeated"), 1))
        limits.enforce(context=context, cols=col_index + repeat - 1)
        effective_repeat = min(repeat, max_col - col_index + 1)
        style_name = child.attributes.get((TABLENS, "style-name"))
        if style_name and effective_repeat > 0:
            width_str = col_style_map.get(str(style_name))
            if width_str:
                cm = _ods_length_to_cm(width_str)
                if cm is not None:
                    excel_width = _ods_cm_to_excel_chars(cm)
                    for i in range(effective_repeat):
                        letter = _column_letters(col_index + i)
                        result[letter] = {"width": excel_width, "source": "workbook"}
        col_index += repeat
    return result if result else None


def _build_ods_column_default_cell_style_map(
    table: Element,
    *,
    max_col: int,
    limits: ParserLimits = DEFAULT_LIMITS,
) -> dict[int, str]:
    """Return {col_index: default_cell_style_name} for table-column elements within max_col.

    Used as a fallback by alignment and rotation extractors: when a cell carries no
    explicit ``table:style-name``, the containing column's ``table:default-cell-style-name``
    provides the style to resolve.  Clipped to ``max_col`` so that LibreOffice sheet-wide
    column fillers do not produce one entry per theoretical column position.
    """
    if max_col <= 0:
        return {}
    result: dict[int, str] = {}
    table_col_name = TableColumn().qname
    table_name = str(table.attributes.get((TABLENS, "name"), "<unnamed>"))
    context = f"ODS sheet '{table_name}' column default cell styles"
    col_index = 1
    for child in table.childNodes:
        if not isinstance(child, Element) or child.qname != table_col_name:
            continue
        if col_index > max_col:
            break
        repeat = int(child.attributes.get((TABLENS, "number-columns-repeated"), 1))
        limits.enforce(context=context, cols=col_index + repeat - 1)
        effective_repeat = min(repeat, max_col - col_index + 1)
        default_style = child.attributes.get((TABLENS, "default-cell-style-name"))
        if default_style and effective_repeat > 0:
            for i in range(effective_repeat):
                result[col_index + i] = str(default_style)
        col_index += repeat
    return result


_ODS_HORIZONTAL_ALIGNMENT_MAP: dict[str, str] = {
    "left": "left",
    "center": "center",
    "right": "right",
    # ODS locale-neutral alignment values: in LTR locales `start` reads as
    # `left` and `end` as `right`. Normalize on read so the canonical
    # representation stays absolute (`left` / `right`), matching what the
    # renderer writes.
    "start": "left",
    "end": "right",
}


def _build_cell_horizontal_alignment_map(doc) -> dict[str, str]:
    """Return mapping {style_name -> canonical horizontal alignment}.

    Reads ``fo:text-align`` from any ``style:paragraph-properties`` child of
    a table-cell style. Out-of-vocabulary values (``justify``, etc.) are
    dropped silently so they do not bloat canonical metadata.
    """
    result: dict[str, str] = {}
    para_props_name = ParagraphProperties().qname
    for style in doc.getElementsByType(Style):
        if style.attributes.get((STYLENS, "family")) != "table-cell":
            continue
        name = style.attributes.get((STYLENS, "name"))
        if not name:
            continue
        for child in style.childNodes:
            if not isinstance(child, Element) or child.qname != para_props_name:
                continue
            raw = child.attributes.get((FONS, "text-align"))
            if raw is None:
                continue
            canonical = _ODS_HORIZONTAL_ALIGNMENT_MAP.get(str(raw).strip().lower())
            if canonical:
                result[str(name)] = canonical
                break
    return result


def _extract_ods_horizontal_alignments(
    table: Element,
    alignment_map: dict[str, str],
    *,
    max_row: int,
    max_col: int,
    limits: ParserLimits = DEFAULT_LIMITS,
) -> dict[str, dict] | None:
    """Return {cell_address: {horizontal, source}} for cells with a canonical
    horizontal alignment style.

    Iteration is clipped to ``max_row`` x ``max_col`` (the parsed content
    extent) so that LibreOffice "select all + left-align" filler patterns do
    not expand ``row_repeat`` x ``col_repeat`` into one metadata entry per
    implied address. ``limits`` is honoured on per-axis and per-cell bases as
    defense-in-depth against inputs that still declare implausible repeats
    within the content extent.  When a cell carries no explicit style the
    column's ``table:default-cell-style-name`` is used as a fallback.
    """
    if max_row <= 0 or max_col <= 0:
        return None
    result: dict[str, dict] = {}
    col_default_style_map = _build_ods_column_default_cell_style_map(
        table, max_col=max_col, limits=limits
    )
    table_row_name = TableRow().qname
    table_cell_name = TableCell().qname
    covered_cell_name = CoveredTableCell().qname
    table_name = str(table.attributes.get((TABLENS, "name"), "<unnamed>"))
    context = f"ODS sheet '{table_name}' horizontal alignments"

    row_index = 1
    for child in table.childNodes:
        if not isinstance(child, Element) or child.qname != table_row_name:
            continue
        if row_index > max_row:
            break
        row_repeat = int(child.attributes.get((TABLENS, "number-rows-repeated"), 1))
        limits.enforce(context=context, rows=row_index + row_repeat - 1)
        effective_row_repeat = min(row_repeat, max_row - row_index + 1)
        col_index = 1
        for cell in child.childNodes:
            if not isinstance(cell, Element) or cell.qname not in (table_cell_name, covered_cell_name):
                continue
            if col_index > max_col:
                break
            col_repeat = int(cell.attributes.get((TABLENS, "number-columns-repeated"), 1))
            limits.enforce(context=context, cols=col_index + col_repeat - 1)
            effective_col_repeat = min(col_repeat, max_col - col_index + 1)
            if (
                cell.qname != covered_cell_name
                and effective_row_repeat > 0
                and effective_col_repeat > 0
            ):
                cell_style_name = (
                    cell.attributes.get((TABLENS, "style-name"))
                    or cell.attributes.get((STYLENS, "style-name"))
                )
                if cell_style_name:
                    canonical = alignment_map.get(str(cell_style_name))
                    if canonical:
                        limits.enforce(
                            context=context,
                            cells=len(result)
                            + effective_row_repeat * effective_col_repeat,
                        )
                        for r_off in range(effective_row_repeat):
                            for c_off in range(effective_col_repeat):
                                addr = (
                                    f"{_column_letters(col_index + c_off)}"
                                    f"{row_index + r_off}"
                                )
                                result[addr] = {
                                    "horizontal": canonical,
                                    "source": "workbook",
                                }
                elif col_default_style_map:
                    # Per-column fallback: each column in a repeated span may
                    # carry a different default-cell-style-name.
                    limits.enforce(
                        context=context,
                        cells=len(result)
                        + effective_row_repeat * effective_col_repeat,
                    )
                    for r_off in range(effective_row_repeat):
                        for c_off in range(effective_col_repeat):
                            fallback_style = col_default_style_map.get(col_index + c_off)
                            if not fallback_style:
                                continue
                            canonical = alignment_map.get(str(fallback_style))
                            if not canonical:
                                continue
                            addr = (
                                f"{_column_letters(col_index + c_off)}"
                                f"{row_index + r_off}"
                            )
                            result[addr] = {
                                "horizontal": canonical,
                                "source": "workbook",
                            }
            col_index += col_repeat
        row_index += row_repeat
    return result if result else None


_ODS_VERTICAL_ALIGNMENT_MAP: dict[str, str] = {
    "top": "top",
    "middle": "center",  # the one intrinsic ODF ↔ OOXML vocabulary remap.
    "bottom": "bottom",
    # `automatic` and any other unmapped value are dropped on read — they are
    # "no value" sentinels by ODF design, and mapping them to a concrete
    # canonical value would synthesise metadata that never existed.
}


def _build_cell_vertical_alignment_map(doc) -> dict[str, str]:
    """Return mapping {style_name -> canonical vertical alignment}.

    Reads ``style:vertical-align`` from any ``style:table-cell-properties``
    child of a table-cell style. Out-of-vocabulary values (``automatic``,
    etc.) are dropped silently so they do not bloat canonical metadata.
    """
    result: dict[str, str] = {}
    cell_props_name = TableCellProperties().qname
    for style in doc.getElementsByType(Style):
        if style.attributes.get((STYLENS, "family")) != "table-cell":
            continue
        name = style.attributes.get((STYLENS, "name"))
        if not name:
            continue
        for child in style.childNodes:
            if not isinstance(child, Element) or child.qname != cell_props_name:
                continue
            raw = child.attributes.get((STYLENS, "vertical-align"))
            if raw is None:
                continue
            canonical = _ODS_VERTICAL_ALIGNMENT_MAP.get(str(raw).strip().lower())
            if canonical:
                result[str(name)] = canonical
                break
    return result


def _extract_ods_vertical_alignments(
    table: Element,
    alignment_map: dict[str, str],
    *,
    max_row: int,
    max_col: int,
    limits: ParserLimits = DEFAULT_LIMITS,
) -> dict[str, dict] | None:
    """Return {cell_address: {vertical, source}} for cells with a canonical
    vertical alignment style.

    Iteration is clipped to ``max_row`` x ``max_col`` (the parsed content
    extent) so that LibreOffice "select all + vertical-center" filler
    patterns do not expand ``row_repeat`` x ``col_repeat`` into one metadata
    entry per implied address. ``limits`` is honoured on per-axis and per-cell
    bases as defense-in-depth against inputs that still declare implausible
    repeats within the content extent.  When a cell carries no explicit style
    the column's ``table:default-cell-style-name`` is used as a fallback.
    """
    if max_row <= 0 or max_col <= 0:
        return None
    result: dict[str, dict] = {}
    col_default_style_map = _build_ods_column_default_cell_style_map(
        table, max_col=max_col, limits=limits
    )
    table_row_name = TableRow().qname
    table_cell_name = TableCell().qname
    covered_cell_name = CoveredTableCell().qname
    table_name = str(table.attributes.get((TABLENS, "name"), "<unnamed>"))
    context = f"ODS sheet '{table_name}' vertical alignments"

    row_index = 1
    for child in table.childNodes:
        if not isinstance(child, Element) or child.qname != table_row_name:
            continue
        if row_index > max_row:
            break
        row_repeat = int(child.attributes.get((TABLENS, "number-rows-repeated"), 1))
        limits.enforce(context=context, rows=row_index + row_repeat - 1)
        effective_row_repeat = min(row_repeat, max_row - row_index + 1)
        col_index = 1
        for cell in child.childNodes:
            if not isinstance(cell, Element) or cell.qname not in (table_cell_name, covered_cell_name):
                continue
            if col_index > max_col:
                break
            col_repeat = int(cell.attributes.get((TABLENS, "number-columns-repeated"), 1))
            limits.enforce(context=context, cols=col_index + col_repeat - 1)
            effective_col_repeat = min(col_repeat, max_col - col_index + 1)
            if (
                cell.qname != covered_cell_name
                and effective_row_repeat > 0
                and effective_col_repeat > 0
            ):
                cell_style_name = (
                    cell.attributes.get((TABLENS, "style-name"))
                    or cell.attributes.get((STYLENS, "style-name"))
                )
                if cell_style_name:
                    canonical = alignment_map.get(str(cell_style_name))
                    if canonical:
                        limits.enforce(
                            context=context,
                            cells=len(result)
                            + effective_row_repeat * effective_col_repeat,
                        )
                        for r_off in range(effective_row_repeat):
                            for c_off in range(effective_col_repeat):
                                addr = (
                                    f"{_column_letters(col_index + c_off)}"
                                    f"{row_index + r_off}"
                                )
                                result[addr] = {
                                    "vertical": canonical,
                                    "source": "workbook",
                                }
                elif col_default_style_map:
                    # Per-column fallback: each column in a repeated span may
                    # carry a different default-cell-style-name.
                    limits.enforce(
                        context=context,
                        cells=len(result)
                        + effective_row_repeat * effective_col_repeat,
                    )
                    for r_off in range(effective_row_repeat):
                        for c_off in range(effective_col_repeat):
                            fallback_style = col_default_style_map.get(col_index + c_off)
                            if not fallback_style:
                                continue
                            canonical = alignment_map.get(str(fallback_style))
                            if not canonical:
                                continue
                            addr = (
                                f"{_column_letters(col_index + c_off)}"
                                f"{row_index + r_off}"
                            )
                            result[addr] = {
                                "vertical": canonical,
                                "source": "workbook",
                            }
            col_index += col_repeat
        row_index += row_repeat
    return result if result else None


def _build_cell_rotation_map(doc) -> dict[str, int]:
    """Return mapping {style_name -> ods_rotation_angle} for table-cell styles with rotation."""
    result: dict[str, int] = {}
    for style in doc.getElementsByType(Style):
        if style.attributes.get((STYLENS, "family")) != "table-cell":
            continue
        name = style.attributes.get((STYLENS, "name"))
        if not name:
            continue
        for child in style.childNodes:
            if not isinstance(child, Element):
                continue
            rotation = child.attributes.get((STYLENS, "rotation-angle"))
            if rotation is not None:
                try:
                    result[str(name)] = int(rotation)
                except (TypeError, ValueError):
                    pass
    return result


def _extract_ods_text_orientations(
    table: Element,
    rotation_map: dict[str, int],
    *,
    max_row: int,
    max_col: int,
    limits: ParserLimits = DEFAULT_LIMITS,
) -> dict[str, dict] | None:
    """Return {cell_address: {rotation, source}} for cells with non-zero XLSX rotation.

    Iteration is clipped to ``max_row`` x ``max_col`` (the parsed content
    extent) so that LibreOffice "select all + rotate" filler patterns do not
    expand ``row_repeat`` x ``col_repeat`` into one metadata entry per implied
    address. ``limits`` is honoured on per-axis and per-cell bases as
    defense-in-depth against inputs that still declare implausible repeats
    within the content extent.  When a cell carries no explicit style the
    column's ``table:default-cell-style-name`` is used as a fallback.
    """
    if max_row <= 0 or max_col <= 0:
        return None
    result: dict[str, dict] = {}
    col_default_style_map = _build_ods_column_default_cell_style_map(
        table, max_col=max_col, limits=limits
    )
    table_row_name = TableRow().qname
    table_cell_name = TableCell().qname
    covered_cell_name = CoveredTableCell().qname
    table_name = str(table.attributes.get((TABLENS, "name"), "<unnamed>"))
    context = f"ODS sheet '{table_name}' text orientations"

    row_index = 1
    for child in table.childNodes:
        if not isinstance(child, Element) or child.qname != table_row_name:
            continue
        if row_index > max_row:
            break
        row_repeat = int(child.attributes.get((TABLENS, "number-rows-repeated"), 1))
        limits.enforce(context=context, rows=row_index + row_repeat - 1)
        effective_row_repeat = min(row_repeat, max_row - row_index + 1)
        col_index = 1
        for cell in child.childNodes:
            if not isinstance(cell, Element) or cell.qname not in (table_cell_name, covered_cell_name):
                continue
            if col_index > max_col:
                break
            col_repeat = int(cell.attributes.get((TABLENS, "number-columns-repeated"), 1))
            limits.enforce(context=context, cols=col_index + col_repeat - 1)
            effective_col_repeat = min(col_repeat, max_col - col_index + 1)
            if (
                cell.qname != covered_cell_name
                and effective_row_repeat > 0
                and effective_col_repeat > 0
            ):
                cell_style_name = (
                    cell.attributes.get((TABLENS, "style-name"))
                    or cell.attributes.get((STYLENS, "style-name"))
                )
                if cell_style_name:
                    ods_rotation = rotation_map.get(str(cell_style_name))
                    if ods_rotation:
                        xlsx_rotation = _ods_rotation_to_xlsx(ods_rotation)
                        if xlsx_rotation > 0:
                            limits.enforce(
                                context=context,
                                cells=len(result)
                                + effective_row_repeat * effective_col_repeat,
                            )
                            for r_off in range(effective_row_repeat):
                                for c_off in range(effective_col_repeat):
                                    addr = (
                                        f"{_column_letters(col_index + c_off)}"
                                        f"{row_index + r_off}"
                                    )
                                    result[addr] = {
                                        "rotation": xlsx_rotation,
                                        "source": "workbook",
                                    }
                elif col_default_style_map:
                    # Per-column fallback: each column in a repeated span may
                    # carry a different default-cell-style-name.
                    limits.enforce(
                        context=context,
                        cells=len(result)
                        + effective_row_repeat * effective_col_repeat,
                    )
                    for r_off in range(effective_row_repeat):
                        for c_off in range(effective_col_repeat):
                            fallback_style = col_default_style_map.get(col_index + c_off)
                            if not fallback_style:
                                continue
                            ods_rotation = rotation_map.get(str(fallback_style))
                            if not ods_rotation:
                                continue
                            xlsx_rotation = _ods_rotation_to_xlsx(ods_rotation)
                            if xlsx_rotation <= 0:
                                continue
                            addr = (
                                f"{_column_letters(col_index + c_off)}"
                                f"{row_index + r_off}"
                            )
                            result[addr] = {
                                "rotation": xlsx_rotation,
                                "source": "workbook",
                            }
            col_index += col_repeat
        row_index += row_repeat
    return result if result else None


def _store_workbook_meta(ir: WorkbookIR, workbook_meta: dict[str, Any]) -> None:
    meta_sheet = ir.hidden_sheets.setdefault("_meta", SheetIR(name="_meta"))
    meta_sheet.meta["_hidden"] = True
    meta_sheet.meta["workbook_meta_blob"] = json.dumps(
        workbook_meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _parse_hidden_style_names(doc) -> set[str]:
    hidden_names: set[str] = set()
    table_properties_name = TableProperties().qname

    for style in doc.getElementsByType(Style):
        if style.attributes.get((STYLENS, "family")) != "table":
            continue
        for child in style.childNodes:
            if not isinstance(child, Element) or child.qname != table_properties_name:
                continue
            if str(child.attributes.get((TABLENS, "display"), "true")).lower() == "false":
                name = style.attributes.get((STYLENS, "name"))
                if name:
                    hidden_names.add(str(name))
    return hidden_names


def _table_is_hidden(table: Element, hidden_style_names: set[str]) -> bool:
    style_name = table.attributes.get((TABLENS, "style-name"))
    if style_name and str(style_name) in hidden_style_names:
        return True
    return str(table.attributes.get((TABLENS, "name"), "")) == "_meta"


def _parse_table_grid(
    table: Element,
    limits: ParserLimits = DEFAULT_LIMITS,
) -> ParsedTable:
    values: dict[tuple[int, int], str] = {}
    merges: list[tuple[int, int, int, int]] = []
    validation_cells: dict[str, list[tuple[int, int]]] = defaultdict(list)

    table_row_name = TableRow().qname
    table_cell_name = TableCell().qname
    covered_cell_name = CoveredTableCell().qname

    row_index = 1
    max_row = 0
    max_col = 0
    table_name = str(table.attributes.get((TABLENS, "name"), "<unnamed>"))
    context = f"ODS sheet '{table_name}'"

    for row in [
        child
        for child in table.childNodes
        if isinstance(child, Element) and child.qname == table_row_name
    ]:
        row_repeat = int(row.attributes.get((TABLENS, "number-rows-repeated"), 1))
        # Keep col_repeat as a descriptor — never expand here, so a row of
        # empty-but-styled filler cells stays O(cell_count_in_row), not
        # O(sum_of_col_repeats).
        row_cells: list[tuple[bool, str, int, int, str | None, int]] = []

        for cell in row.childNodes:
            if not isinstance(cell, Element) or cell.qname not in (
                table_cell_name,
                covered_cell_name,
            ):
                continue
            col_repeat = int(cell.attributes.get((TABLENS, "number-columns-repeated"), 1))
            if cell.qname == covered_cell_name:
                row_cells.append((True, "", 1, 1, None, col_repeat))
            else:
                row_span = int(cell.attributes.get((TABLENS, "number-rows-spanned"), 1))
                col_span = int(cell.attributes.get((TABLENS, "number-columns-spanned"), 1))
                validation_name = cell.attributes.get((TABLENS, "content-validation-name"))
                row_cells.append(
                    (
                        False,
                        _cell_value(cell),
                        row_span,
                        col_span,
                        str(validation_name) if validation_name else None,
                        col_repeat,
                    )
                )

        row_has_content = any(
            (not covered)
            and (value != "" or row_span > 1 or col_span > 1 or validation_name is not None)
            for covered, value, row_span, col_span, validation_name, _ in row_cells
        )

        if not row_has_content:
            # Repeated empty filler block — skip materialization entirely.
            # No values, no merges, no validations, and no extension of
            # max_row / max_col so downstream extent scans do not iterate the
            # full theoretical sheet either.
            row_index += row_repeat
            continue

        # Defense-in-depth: confirm the declared block dimensions are within
        # configured limits before iterating. The local skip above already
        # neutralizes the common LibreOffice "select-all + format" pattern;
        # this check protects against inputs that declare implausibly large
        # repeats on rows that do carry content.
        projected_row = row_index + row_repeat - 1
        projected_col = 0
        projected_content_cols_per_row = 0
        running_col = 1
        for covered, value, row_span, col_span, validation_name, col_repeat in row_cells:
            has_cell_content = (not covered) and (
                value != "" or row_span > 1 or col_span > 1 or validation_name is not None
            )
            if has_cell_content:
                cell_right = running_col + col_repeat - 1 + (col_span - 1 if col_span > 1 else 0)
                if cell_right > projected_col:
                    projected_col = cell_right
                projected_content_cols_per_row += col_repeat
            running_col += col_repeat
        limits.enforce(
            context=context,
            rows=projected_row,
            cols=projected_col,
            cells=len(values) + row_repeat * projected_content_cols_per_row,
        )

        for repeated_row in range(row_repeat):
            absolute_row = row_index + repeated_row
            col_index = 1
            for covered, value, row_span, col_span, validation_name, col_repeat in row_cells:
                has_cell_content = (not covered) and (
                    value != "" or row_span > 1 or col_span > 1 or validation_name is not None
                )
                if not has_cell_content:
                    col_index += col_repeat
                    continue
                for offset in range(col_repeat):
                    absolute_col = col_index + offset
                    values[(absolute_row, absolute_col)] = value
                    if row_span > 1 or col_span > 1:
                        merges.append(
                            (
                                absolute_row,
                                absolute_col,
                                absolute_row + row_span - 1,
                                absolute_col + col_span - 1,
                            )
                        )
                    if validation_name:
                        validation_cells[validation_name].append((absolute_row, absolute_col))
                    # Bounds must include the full span of an explicit merge:
                    # downstream extent scans and header-merge extraction rely
                    # on max_col / max_row reaching the right/bottom edge of
                    # the merge, not just its anchor.
                    span_right = absolute_col + col_span - 1
                    if span_right > max_col:
                        max_col = span_right
                    span_bottom = absolute_row + row_span - 1
                    if span_bottom > max_row:
                        max_row = span_bottom
                col_index += col_repeat
        row_index += row_repeat

    return ParsedTable(
        values=values,
        merges=merges,
        validation_cells=dict(validation_cells),
        max_row=max_row,
        max_col=max_col,
    )


def _parse_hidden_sheet(table: Element, limits: ParserLimits = DEFAULT_LIMITS) -> SheetIR:
    parsed = _parse_table_grid(table, limits=limits)
    sheet = SheetIR(name=str(table.attributes.get((TABLENS, "name"), "_meta")))
    sheet.meta["_hidden"] = True
    for row in range(1, parsed.max_row + 1):
        key = str(parsed.values.get((row, 1), "") or "")
        value = str(parsed.values.get((row, 2), "") or "")
        if key:
            sheet.meta[key] = value
    return sheet


def _read_meta_payload(sheet: SheetIR) -> dict[str, Any]:
    blob = sheet.meta.get("workbook_meta_blob", "")
    if blob:
        try:
            result = json.loads(str(blob))
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            # legacy: pre-JSON repr format
            result = ast.literal_eval(str(blob))
            if isinstance(result, dict):
                return result
        except (ValueError, SyntaxError, TypeError):
            pass
    return {key: value for key, value in sheet.meta.items() if key != "_hidden"}


def _legend_table_hints(
    workbook_meta: dict[str, Any],
    *,
    sheet_name: str,
) -> list[dict[str, Any]]:
    raw = workbook_meta.get("legend_blocks") if isinstance(workbook_meta, dict) else None
    if not isinstance(raw, dict):
        return []

    hints: list[dict[str, Any]] = []
    for legend_name, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        resolved = spec.get("resolved")
        if not isinstance(resolved, dict):
            continue
        if str(resolved.get("sheet")) != sheet_name:
            continue
        try:
            hints.append(
                {
                    "name": str(legend_name),
                    "frame_name": str(resolved.get("frame_name") or f"legend_{legend_name}"),
                    "top": int(resolved["top"]),
                    "left": int(resolved["left"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return hints


def _apply_legend_table_hints(sheet: SheetIR, hints: list[dict[str, Any]]) -> None:
    if not hints:
        return
    by_position = {(int(hint["top"]), int(hint["left"])): hint for hint in hints}
    for table in sheet.tables:
        hint = by_position.get((table.top, table.left))
        if not hint:
            continue
        table.kind = "legend"
        table.frame_name = str(hint["frame_name"])


_ADDRESS_RE = re.compile(
    r"^(?P<sheet>'(?:[^']|'')+'|[^.:\s]+)\.(?P<start>\$?[A-Z]+\$?\d+)"
    r"(?::(?:(?P<sheet2>'(?:[^']|'')+'|[^.:\s]+)\.)?(?P<end>\$?[A-Z]+\$?\d+))?$"
)


def _unquote_sheet_name(name: str) -> str:
    if name.startswith("'") and name.endswith("'"):
        return name[1:-1].replace("''", "'")
    return name


def _parse_cell_ref(ref: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?(?P<col>[A-Z]+)\$?(?P<row>\d+)", ref)
    if not match:
        raise ValueError(f"Unsupported ODS cell reference: {ref}")
    return int(match.group("row")), _column_index(match.group("col"))


def _parse_range_address(address: str) -> tuple[str, int, int, int, int]:
    match = _ADDRESS_RE.fullmatch(address.strip())
    if not match:
        raise ValueError(f"Unsupported ODS range address: {address}")
    sheet = _unquote_sheet_name(match.group("sheet"))
    sheet2 = _unquote_sheet_name(match.group("sheet2")) if match.group("sheet2") else sheet
    if sheet2 != sheet:
        raise ValueError(f"Cross-sheet ranges are not supported here: {address}")
    r1, c1 = _parse_cell_ref(match.group("start"))
    end_ref = match.group("end") or match.group("start")
    r2, c2 = _parse_cell_ref(end_ref)
    return sheet, r1, c1, r2, c2


def _parse_validation_formula(condition: str) -> ListLiteralFormulaSpec | None:
    match = re.search(r"cell-content-is-in-list\((?P<body>.*)\)", condition)
    if not match:
        return None
    body = match.group("body")
    try:
        values = next(csv.reader([body], delimiter=";", quotechar='"'))
    except csv.Error:
        return None
    return ListLiteralFormulaSpec(tuple(values))


def _extract_validations(
    parsed: ParsedTable,
    validation_defs: dict[str, str],
) -> list[DataValidationSpec]:
    validations: list[DataValidationSpec] = []

    for name, coords in parsed.validation_cells.items():
        condition = validation_defs.get(name)
        if not condition:
            continue
        formula = _parse_validation_formula(condition)
        if not formula:
            continue
        rows = [row for row, _ in coords]
        cols = [col for _, col in coords]
        validations.append(
            DataValidationSpec(
                kind="list",
                area=(min(rows), min(cols), max(rows), max(cols)),
                formula=formula,
                allow_empty=True,
            )
        )

    return validations


def _extract_named_ranges(table: Element, *, sheet_name: str) -> list[NamedRange]:
    named_ranges: list[NamedRange] = []
    for named_range in table.getElementsByType(OdfNamedRange):
        name = named_range.attributes.get((TABLENS, "name"))
        address = named_range.attributes.get((TABLENS, "cell-range-address"))
        if not name or not address:
            continue
        try:
            range_sheet, r1, c1, r2, c2 = _parse_range_address(str(address))
        except ValueError:
            continue
        if range_sheet != sheet_name:
            continue
        named_ranges.append(NamedRange(name=str(name), sheet=sheet_name, area=(r1, c1, r2, c2)))
    return named_ranges


def _extract_autofilter_ref(database_ranges: list[Element], *, sheet_name: str) -> str | None:
    for database_range in database_ranges:
        address = database_range.attributes.get((TABLENS, "target-range-address"))
        if not address:
            continue
        try:
            range_sheet, r1, c1, r2, c2 = _parse_range_address(str(address))
        except ValueError:
            continue
        if range_sheet != sheet_name:
            continue
        return f"{_column_letters(c1)}{r1}:{_column_letters(c2)}{r2}"
    return None


def parse_workbook(
    path: str | Path,
    *,
    limits: ParserLimits = DEFAULT_LIMITS,
) -> WorkbookIR:
    """Parse an ODS workbook into WorkbookIR."""
    doc = load(str(path))
    ir = WorkbookIR()

    hidden_style_names = _parse_hidden_style_names(doc)
    tables = [
        table for table in doc.getElementsByType(Table) if table.parentNode == doc.spreadsheet
    ]
    validation_defs: dict[str, str] = {}
    for validation in doc.spreadsheet.getElementsByType(OdfContentValidation):
        name = validation.attributes.get((TABLENS, "name"))
        condition = validation.attributes.get((TABLENS, "condition"))
        if name and condition:
            validation_defs[str(name)] = str(condition)
    database_ranges = [
        database_range for database_range in doc.spreadsheet.getElementsByType(DatabaseRange)
    ]

    meta_payload: dict[str, Any] = {}

    for table in tables:
        name = str(table.attributes.get((TABLENS, "name"), "Sheet1"))
        if _table_is_hidden(table, hidden_style_names):
            hidden_sheet = _parse_hidden_sheet(table, limits=limits)
            ir.hidden_sheets[name] = hidden_sheet
            if name == "_meta":
                meta_payload = _read_meta_payload(hidden_sheet)
            continue

    col_style_map = _build_column_style_map(doc)
    rotation_map = _build_cell_rotation_map(doc)
    horizontal_alignment_map = _build_cell_horizontal_alignment_map(doc)
    vertical_alignment_map = _build_cell_vertical_alignment_map(doc)
    meta_changed = False

    for table in tables:
        name = str(table.attributes.get((TABLENS, "name"), "Sheet1"))
        if name in ir.hidden_sheets:
            continue

        parsed = _parse_table_grid(table, limits=limits)
        meta_hints = build_sheet_meta_hints(meta_payload, sheet_name=name)
        validations = _extract_validations(parsed, validation_defs)
        autofilter_ref = _extract_autofilter_ref(database_ranges, sheet_name=name)
        legend_hints = _legend_table_hints(meta_payload, sheet_name=name)
        legend_anchors = [
            (hint["top"], hint["left"])
            for hint in legend_hints
            if isinstance(hint.get("top"), int) and isinstance(hint.get("left"), int)
        ]
        sheet = build_visible_sheet_ir(
            parsed,
            sheet_name=name,
            meta_hints=meta_hints,
            validations=validations,
            autofilter_ref=autofilter_ref,
            anchors=[(1, 1), *legend_anchors] if legend_anchors else None,
            stop_on_empty_col=bool(legend_anchors),
        )
        _apply_legend_table_hints(sheet, legend_hints)
        sheet.named_ranges = _extract_named_ranges(table, sheet_name=name)

        column_widths = _extract_ods_column_widths(
            table, col_style_map, max_col=parsed.max_col, limits=limits
        )
        if column_widths:
            sheet.meta["__column_widths"] = column_widths

        text_orientations = _extract_ods_text_orientations(
            table,
            rotation_map,
            max_row=parsed.max_row,
            max_col=parsed.max_col,
            limits=limits,
        )
        if text_orientations:
            sheet.meta["__text_orientations"] = text_orientations

        horizontal_alignments = _extract_ods_horizontal_alignments(
            table,
            horizontal_alignment_map,
            max_row=parsed.max_row,
            max_col=parsed.max_col,
            limits=limits,
        )
        if horizontal_alignments:
            sheet.meta["__horizontal_alignments"] = horizontal_alignments

        vertical_alignments = _extract_ods_vertical_alignments(
            table,
            vertical_alignment_map,
            max_row=parsed.max_row,
            max_col=parsed.max_col,
            limits=limits,
        )
        if vertical_alignments:
            sheet.meta["__vertical_alignments"] = vertical_alignments

        # Carrier is authoritative for all four presentation-metadata
        # families: empty extraction must clear any persisted entry for
        # that sheet so the next roundtrip cannot silently reapply
        # formatting the user has just removed. The shared helper is
        # invoked unconditionally per family for that reason.
        if apply_cell_addressed_presentation_meta(
            meta_payload, name, "column_widths", column_widths
        ):
            meta_changed = True
        if apply_cell_addressed_presentation_meta(
            meta_payload, name, "text_orientations", text_orientations
        ):
            meta_changed = True
        if apply_cell_addressed_presentation_meta(
            meta_payload, name, "horizontal_alignments", horizontal_alignments
        ):
            meta_changed = True
        if apply_cell_addressed_presentation_meta(
            meta_payload, name, "vertical_alignments", vertical_alignments
        ):
            meta_changed = True

        ir.sheets[name] = sheet

    if meta_changed:
        _store_workbook_meta(ir, meta_payload)

    return ir


__all__ = ["parse_workbook"]
