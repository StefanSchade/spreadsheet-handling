from __future__ import annotations

import ast
from pathlib import Path

import pytest

import spreadsheet_handling.io_backends.ods.odf_parser as op
from spreadsheet_handling.io_backends.ods.parser_interpretation import (
    ParsedTable,
    build_sheet_meta_hints,
    build_visible_sheet_ir,
)
from spreadsheet_handling.rendering.ir import DataValidationSpec


pytestmark = pytest.mark.ftr("FTR-ODS-CALC-ADAPTER-IMPLEMENTATION-P3J")


def test_build_sheet_meta_hints_merges_workbook_defaults_and_sheet_overrides():
    workbook_meta = {
        "freeze_header": True,
        "auto_filter": True,
        "helper_prefix": "_",
        "sheets": {
            "Products": {
                "freeze_header": False,
                "header_fill_rgb": "#CCE5FF",
            }
        },
    }

    hints = build_sheet_meta_hints(workbook_meta, sheet_name="Products")

    assert hints == {
        "freeze_header": False,
        "auto_filter": True,
        "helper_prefix": "_",
        "header_fill_rgb": "#CCE5FF",
    }


def test_build_visible_sheet_ir_combines_interpretation_inputs():
    parsed = ParsedTable(
        values={
            (1, 1): "id",
            (1, 2): "title",
            (2, 1): "P-001",
            (2, 2): "Alpha",
        },
        merges=[],
        validation_cells={},
        max_row=2,
        max_col=2,
    )
    validations = [
        DataValidationSpec(
            kind="list",
            area=(2, 2, 2, 2),
            formula='"new,done"',
            allow_empty=True,
        )
    ]

    sheet = build_visible_sheet_ir(
        parsed,
        sheet_name="Products",
        meta_hints={"freeze_header": True, "auto_filter": True},
        validations=validations,
        autofilter_ref="A1:B2",
    )

    assert sheet.meta["options"] == {"freeze_header": True, "auto_filter": True}
    assert sheet.meta["__autofilter_ref"] == "A1:B2"
    assert sheet.validations == validations
    assert sheet.tables[0].headers == ["id", "title"]
    assert sheet.tables[0].data == [["P-001", "Alpha"]]


def test_odf_parser_delegates_visible_sheet_interpretation_to_helper_module():
    module_path = Path(op.__file__).resolve()
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    imported_modules: list[str] = []
    defined_functions: list[str] = []
    called_functions: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.append(node.module or "")
        elif isinstance(node, ast.FunctionDef):
            defined_functions.append(node.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_functions.append(node.func.id)

    assert "spreadsheet_handling.io_backends.ods.parser_interpretation" in imported_modules
    assert "_parse_table_grid" in defined_functions
    assert "build_visible_sheet_ir" in called_functions
