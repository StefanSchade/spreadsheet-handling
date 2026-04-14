from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from odf.opendocument import OpenDocumentSpreadsheet
from odf.style import Style, TableCellProperties, TableProperties, TextProperties
from odf.table import (
    ContentValidation,
    ContentValidations,
    CoveredTableCell,
    DatabaseRange,
    DatabaseRanges,
    NamedExpressions,
    NamedRange,
    Table,
    TableCell,
    TableRow,
)
from odf.text import P

from spreadsheet_handling.rendering.plan import (
    AddValidation,
    ApplyColumnStyle,
    ApplyHeaderStyle,
    DefineNamedRange,
    DefineSheet,
    MergeCells,
    RenderPlan,
    SetAutoFilter,
    SetFreeze,
    SetHeader,
    WriteDataBlock,
    WriteMeta,
)


@dataclass
class _BufferedCell:
    value: Any = ""
    bold: bool = False
    fill_rgb: str | None = None
    row_span: int = 1
    col_span: int = 1
    covered: bool = False
    validation_name: str | None = None


@dataclass
class _BufferedSheet:
    name: str
    hidden: bool = False
    cells: dict[tuple[int, int], _BufferedCell] = field(default_factory=dict)
    named_ranges: list[DefineNamedRange] = field(default_factory=list)
    validations: list[AddValidation] = field(default_factory=list)
    autofilter: tuple[int, int, int, int] | None = None
    freeze: tuple[int, int] | None = None
    max_row: int = 0
    max_col: int = 0

    def ensure_cell(self, row: int, col: int) -> _BufferedCell:
        self.max_row = max(self.max_row, row)
        self.max_col = max(self.max_col, col)
        return self.cells.setdefault((row, col), _BufferedCell())


def _column_letters(index: int) -> str:
    letters = ""
    n = index
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters or "A"


def _quote_sheet_name(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def _cell_address(sheet: str, row: int, col: int) -> str:
    return f"{_quote_sheet_name(sheet)}.{_column_letters(col)}{row}"


def _range_address(sheet: str, r1: int, c1: int, r2: int, c2: int) -> str:
    return f"{_cell_address(sheet, r1, c1)}:{_cell_address(sheet, r2, c2)}"


def _sheet_validation_name(sheet: str, index: int) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", sheet).strip("_") or "sheet"
    return f"{safe}_validation_{index}"


def _style_key(*, bold: bool, fill_rgb: str | None) -> tuple[bool, str | None]:
    return bold, fill_rgb.upper() if fill_rgb else None


def _register_cell_style(
    doc: OpenDocumentSpreadsheet,
    cache: dict[tuple[bool, str | None], str],
    *,
    bold: bool,
    fill_rgb: str | None,
) -> str | None:
    key = _style_key(bold=bold, fill_rgb=fill_rgb)
    if key == (False, None):
        return None
    if key in cache:
        return cache[key]

    style_name = f"cell_style_{len(cache) + 1}"
    style = Style(name=style_name, family="table-cell")
    if fill_rgb:
        style.addElement(TableCellProperties(backgroundcolor=fill_rgb))
    if bold:
        style.addElement(TextProperties(fontweight="bold"))
    doc.automaticstyles.addElement(style)
    cache[key] = style_name
    return style_name


def _register_hidden_table_style(
    doc: OpenDocumentSpreadsheet,
    cache: dict[str, str],
) -> str:
    if "hidden_table" in cache:
        return cache["hidden_table"]

    style_name = "hidden_table_style"
    style = Style(name=style_name, family="table")
    style.addElement(TableProperties(display="false"))
    doc.automaticstyles.addElement(style)
    cache["hidden_table"] = style_name
    return style_name


def _parse_xlsx_csv_formula(formula: str) -> list[str]:
    text = str(formula or "")
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    if not text:
        return []
    return next(csv.reader([text], delimiter=",", quotechar='"'))


def _ods_validation_condition(formula: str) -> str:
    values = _parse_xlsx_csv_formula(formula)
    quoted = ";".join(f'"{value.replace(chr(34), chr(34) * 2)}"' for value in values)
    return f"of:cell-content-is-in-list({quoted})"


def _collect_sheets(plan: RenderPlan) -> list[_BufferedSheet]:
    sheets: dict[str, _BufferedSheet] = {}
    ordered_names: list[str] = []

    def ensure_sheet(name: str, *, hidden: bool = False) -> _BufferedSheet:
        sheet = sheets.get(name)
        if sheet is None:
            sheet = _BufferedSheet(name=name, hidden=hidden)
            sheets[name] = sheet
            ordered_names.append(name)
        if hidden:
            sheet.hidden = True
        return sheet

    for op in plan.ops:
        if isinstance(op, DefineSheet):
            ensure_sheet(op.sheet)
            continue

        if isinstance(op, WriteMeta):
            sheet = ensure_sheet(op.sheet or "_meta", hidden=bool(op.hidden))
            row = 1
            for key, value in op.kv.items():
                sheet.ensure_cell(row, 1).value = str(key)
                sheet.ensure_cell(row, 2).value = str(value)
                row += 1
            continue

        sheet_name = getattr(op, "sheet", None)
        if not sheet_name:
            continue
        sheet = ensure_sheet(sheet_name)

        if isinstance(op, SetHeader):
            sheet.ensure_cell(op.row, op.col).value = op.text
            continue

        if isinstance(op, WriteDataBlock):
            for row_offset, row_data in enumerate(op.data):
                for col_offset, value in enumerate(row_data):
                    sheet.ensure_cell(op.r1 + row_offset, op.c1 + col_offset).value = value
            continue

        if isinstance(op, ApplyHeaderStyle):
            cell = sheet.ensure_cell(op.row, op.col)
            cell.bold = cell.bold or bool(op.bold)
            cell.fill_rgb = op.fill_rgb or cell.fill_rgb
            continue

        if isinstance(op, ApplyColumnStyle):
            for row in range(op.from_row, op.to_row + 1):
                cell = sheet.ensure_cell(row, op.col)
                cell.fill_rgb = op.fill_rgb or cell.fill_rgb
            continue

        if isinstance(op, MergeCells):
            anchor = sheet.ensure_cell(op.r1, op.c1)
            anchor.row_span = max(anchor.row_span, op.r2 - op.r1 + 1)
            anchor.col_span = max(anchor.col_span, op.c2 - op.c1 + 1)
            for row in range(op.r1, op.r2 + 1):
                for col in range(op.c1, op.c2 + 1):
                    if (row, col) == (op.r1, op.c1):
                        continue
                    covered = sheet.ensure_cell(row, col)
                    covered.covered = True
            continue

        if isinstance(op, AddValidation):
            sheet.validations.append(op)
            continue

        if isinstance(op, DefineNamedRange):
            sheet.named_ranges.append(op)
            continue

        if isinstance(op, SetAutoFilter):
            sheet.autofilter = (op.r1, op.c1, op.r2, op.c2)
            continue

        if isinstance(op, SetFreeze):
            sheet.freeze = (op.row, op.col)
            continue

    return [sheets[name] for name in ordered_names]


def _build_table(
    doc: OpenDocumentSpreadsheet,
    sheet: _BufferedSheet,
    *,
    cell_style_cache: dict[tuple[bool, str | None], str],
    table_style_cache: dict[str, str],
    spreadsheet_validations: ContentValidations | None,
    spreadsheet_database_ranges: DatabaseRanges | None,
) -> Table:
    table_kwargs: dict[str, Any] = {"name": sheet.name}
    if sheet.hidden:
        table_kwargs["stylename"] = _register_hidden_table_style(doc, table_style_cache)
    table = Table(**table_kwargs)

    if sheet.validations and spreadsheet_validations is not None:
        for index, validation in enumerate(sheet.validations, start=1):
            validation_name = _sheet_validation_name(sheet.name, index)
            spreadsheet_validations.addElement(
                ContentValidation(
                    name=validation_name,
                    basecelladdress=_cell_address(sheet.name, validation.r1, validation.c1),
                    allowemptycell=str(bool(validation.allow_empty)).lower(),
                    displaylist="unsorted",
                    condition=_ods_validation_condition(validation.formula),
                )
            )
            for row in range(validation.r1, validation.r2 + 1):
                for col in range(validation.c1, validation.c2 + 1):
                    sheet.ensure_cell(row, col).validation_name = validation_name

    if sheet.autofilter and spreadsheet_database_ranges is not None:
        r1, c1, r2, c2 = sheet.autofilter
        spreadsheet_database_ranges.addElement(
            DatabaseRange(
                name=f"{re.sub(r'[^A-Za-z0-9_]', '_', sheet.name) or 'sheet'}_filter",
                targetrangeaddress=_range_address(sheet.name, r1, c1, r2, c2),
                containsheader="true",
                displayfilterbuttons="true",
            )
        )

    if sheet.named_ranges:
        named_expressions = NamedExpressions()
        for named_range in sheet.named_ranges:
            named_expressions.addElement(
                NamedRange(
                    name=named_range.name,
                    basecelladdress=_cell_address(sheet.name, named_range.r1, named_range.c1),
                    cellrangeaddress=_range_address(
                        sheet.name,
                        named_range.r1,
                        named_range.c1,
                        named_range.r2,
                        named_range.c2,
                    ),
                )
            )
        table.addElement(named_expressions)

    max_row = max(sheet.max_row, 1)
    max_col = max(sheet.max_col, 1)

    for row_index in range(1, max_row + 1):
        row = TableRow()
        for col_index in range(1, max_col + 1):
            cell = sheet.cells.get((row_index, col_index))
            if cell and cell.covered:
                row.addElement(CoveredTableCell())
                continue

            attributes: dict[str, Any] = {}
            if cell:
                style_name = _register_cell_style(
                    doc,
                    cell_style_cache,
                    bold=cell.bold,
                    fill_rgb=cell.fill_rgb,
                )
                if style_name:
                    attributes["stylename"] = style_name
                if cell.validation_name:
                    attributes["contentvalidationname"] = cell.validation_name
                if cell.row_span > 1:
                    attributes["numberrowsspanned"] = cell.row_span
                if cell.col_span > 1:
                    attributes["numbercolumnsspanned"] = cell.col_span

            value = "" if cell is None else cell.value
            if value in (None, ""):
                table_cell = TableCell(attributes=attributes)
            elif isinstance(value, bool):
                display = "TRUE" if value else "FALSE"
                table_cell = TableCell(
                    valuetype="boolean",
                    booleanvalue=str(value).lower(),
                    attributes=attributes,
                )
                table_cell.addElement(P(text=display))
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                table_cell = TableCell(
                    valuetype="float",
                    value=value,
                    attributes=attributes,
                )
                table_cell.addElement(P(text=str(value)))
            else:
                text = str(value)
                table_cell = TableCell(
                    valuetype="string",
                    stringvalue=text,
                    attributes=attributes,
                )
                table_cell.addElement(P(text=text))

            row.addElement(table_cell)
        table.addElement(row)

    return table


def _add_freeze_settings(
    doc: OpenDocumentSpreadsheet,
    freeze_sheets: dict[str, tuple[int, int]],
) -> None:
    from odf.config import (
        ConfigItem,
        ConfigItemMapEntry,
        ConfigItemMapIndexed,
        ConfigItemMapNamed,
        ConfigItemSet,
    )

    if not freeze_sheets:
        return

    config_item_set = ConfigItemSet(name="ooo:view-settings")
    doc.settings.addElement(config_item_set)

    indexed = ConfigItemMapIndexed(name="Views")
    config_item_set.addElement(indexed)

    view_entry = ConfigItemMapEntry()
    indexed.addElement(view_entry)

    tables = ConfigItemMapNamed(name="Tables")
    view_entry.addElement(tables)

    for sheet_name, (row, col) in freeze_sheets.items():
        table_entry = ConfigItemMapEntry(name=sheet_name)
        tables.addElement(table_entry)

        row_split = max(row - 1, 0)
        col_split = max(col - 1, 0)
        table_entry.addElement(ConfigItem(name="HorizontalSplitMode", type="short", text="2"))
        table_entry.addElement(ConfigItem(name="VerticalSplitMode", type="short", text="2"))
        table_entry.addElement(ConfigItem(name="HorizontalSplitPosition", type="int", text=str(row_split)))
        table_entry.addElement(ConfigItem(name="VerticalSplitPosition", type="int", text=str(col_split)))
        table_entry.addElement(ConfigItem(name="PositionRight", type="int", text=str(row_split)))
        table_entry.addElement(ConfigItem(name="PositionBottom", type="int", text=str(col_split)))


def render_workbook(plan: RenderPlan, out_path: Path | str) -> None:
    """Render a backend-neutral RenderPlan to an ODS file."""
    doc = OpenDocumentSpreadsheet()
    cell_style_cache: dict[tuple[bool, str | None], str] = {}
    table_style_cache: dict[str, str] = {}

    sheets = _collect_sheets(plan)
    spreadsheet_validations = ContentValidations() if any(sheet.validations for sheet in sheets) else None
    spreadsheet_database_ranges = DatabaseRanges() if any(sheet.autofilter for sheet in sheets) else None
    if spreadsheet_validations is not None:
        doc.spreadsheet.addElement(spreadsheet_validations)
    if spreadsheet_database_ranges is not None:
        doc.spreadsheet.addElement(spreadsheet_database_ranges)

    freeze_sheets: dict[str, tuple[int, int]] = {}
    for sheet in sheets:
        doc.spreadsheet.addElement(
            _build_table(
                doc,
                sheet,
                cell_style_cache=cell_style_cache,
                table_style_cache=table_style_cache,
                spreadsheet_validations=spreadsheet_validations,
                spreadsheet_database_ranges=spreadsheet_database_ranges,
            )
        )
        if sheet.freeze:
            freeze_sheets[sheet.name] = sheet.freeze

    _add_freeze_settings(doc, freeze_sheets)

    out = Path(out_path)
    doc.save(str(out.with_suffix(".ods")))


__all__ = ["render_workbook"]
