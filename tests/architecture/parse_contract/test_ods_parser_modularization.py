from __future__ import annotations

import ast
from pathlib import Path

import pytest

import spreadsheet_handling.io_backends.ods.odf_parser as op


pytestmark = pytest.mark.ftr("FTR-ODS-CALC-ADAPTER-IMPLEMENTATION-P3J")


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
