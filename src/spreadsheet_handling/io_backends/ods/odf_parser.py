from __future__ import annotations

import ast
from collections import defaultdict
import csv
import json
from pathlib import Path
import re
from typing import Any

from odf.element import Element
from odf.namespaces import OFFICENS, STYLENS, TABLENS, TEXTNS
from odf.opendocument import load
from odf.style import Style, TableProperties
from odf.table import (
    ContentValidation as OdfContentValidation,
    CoveredTableCell,
    DatabaseRange,
    NamedRange as OdfNamedRange,
    Table,
    TableCell,
    TableRow,
)
from odf.text import S

from spreadsheet_handling.io_backends.ods.parser_interpretation import (
    ParsedTable,
    build_sheet_meta_hints,
    build_visible_sheet_ir,
)
from spreadsheet_handling.rendering.ir import (
    DataValidationSpec,
    NamedRange,
    SheetIR,
    WorkbookIR,
)
from spreadsheet_handling.rendering.formulas import ListLiteralFormulaSpec


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


def _parse_table_grid(table: Element) -> ParsedTable:
    values: dict[tuple[int, int], str] = {}
    merges: list[tuple[int, int, int, int]] = []
    validation_cells: dict[str, list[tuple[int, int]]] = defaultdict(list)

    table_row_name = TableRow().qname
    table_cell_name = TableCell().qname
    covered_cell_name = CoveredTableCell().qname

    row_index = 1
    max_row = 0
    max_col = 0

    for row in [child for child in table.childNodes if isinstance(child, Element) and child.qname == table_row_name]:
        row_repeat = int(row.attributes.get((TABLENS, "number-rows-repeated"), 1))
        cell_entries: list[tuple[bool, str, int, int, str | None]] = []

        for cell in row.childNodes:
            if not isinstance(cell, Element) or cell.qname not in (table_cell_name, covered_cell_name):
                continue
            col_repeat = int(cell.attributes.get((TABLENS, "number-columns-repeated"), 1))
            row_span = int(cell.attributes.get((TABLENS, "number-rows-spanned"), 1))
            col_span = int(cell.attributes.get((TABLENS, "number-columns-spanned"), 1))
            validation_name = cell.attributes.get((TABLENS, "content-validation-name"))
            if cell.qname == covered_cell_name:
                cell_entries.extend([(True, "", 1, 1, None)] * col_repeat)
            else:
                entry = (
                    False,
                    _cell_value(cell),
                    row_span,
                    col_span,
                    str(validation_name) if validation_name else None,
                )
                cell_entries.extend([entry] * col_repeat)

        for repeated_row in range(row_repeat):
            col_index = 1
            for covered, value, row_span, col_span, validation_name in cell_entries:
                if not covered:
                    values[(row_index + repeated_row, col_index)] = value
                    if row_span > 1 or col_span > 1:
                        merges.append(
                            (
                                row_index + repeated_row,
                                col_index,
                                row_index + repeated_row + row_span - 1,
                                col_index + col_span - 1,
                            )
                        )
                    if validation_name:
                        validation_cells[validation_name].append((row_index + repeated_row, col_index))
                max_col = max(max_col, col_index)
                col_index += 1
            max_row = max(max_row, row_index + repeated_row)
        row_index += row_repeat

    return ParsedTable(
        values=values,
        merges=merges,
        validation_cells=dict(validation_cells),
        max_row=max_row,
        max_col=max_col,
    )


def _parse_hidden_sheet(table: Element) -> SheetIR:
    parsed = _parse_table_grid(table)
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
            result = ast.literal_eval(str(blob))
            if isinstance(result, dict):
                return result
        except (ValueError, SyntaxError):
            pass
    return {key: value for key, value in sheet.meta.items() if key != "_hidden"}


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


def parse_workbook(path: str | Path) -> WorkbookIR:
    """Parse an ODS workbook into WorkbookIR."""
    doc = load(str(path))
    ir = WorkbookIR()

    hidden_style_names = _parse_hidden_style_names(doc)
    tables = [table for table in doc.getElementsByType(Table) if table.parentNode == doc.spreadsheet]
    validation_defs: dict[str, str] = {}
    for validation in doc.spreadsheet.getElementsByType(OdfContentValidation):
        name = validation.attributes.get((TABLENS, "name"))
        condition = validation.attributes.get((TABLENS, "condition"))
        if name and condition:
            validation_defs[str(name)] = str(condition)
    database_ranges = [database_range for database_range in doc.spreadsheet.getElementsByType(DatabaseRange)]

    meta_payload: dict[str, Any] = {}

    for table in tables:
        name = str(table.attributes.get((TABLENS, "name"), "Sheet1"))
        if _table_is_hidden(table, hidden_style_names):
            hidden_sheet = _parse_hidden_sheet(table)
            ir.hidden_sheets[name] = hidden_sheet
            if name == "_meta":
                meta_payload = _read_meta_payload(hidden_sheet)
            continue

    for table in tables:
        name = str(table.attributes.get((TABLENS, "name"), "Sheet1"))
        if name in ir.hidden_sheets:
            continue

        parsed = _parse_table_grid(table)
        meta_hints = build_sheet_meta_hints(meta_payload, sheet_name=name)
        validations = _extract_validations(parsed, validation_defs)
        autofilter_ref = _extract_autofilter_ref(database_ranges, sheet_name=name)
        sheet = build_visible_sheet_ir(
            parsed,
            sheet_name=name,
            meta_hints=meta_hints,
            validations=validations,
            autofilter_ref=autofilter_ref,
        )
        sheet.named_ranges = _extract_named_ranges(table, sheet_name=name)
        ir.sheets[name] = sheet

    return ir


__all__ = ["parse_workbook"]
