"""Parse-contract guard for the XLSX parser interpretation seam.

This check ensures the XLSX parser delegates visible-sheet interpretation to
its adapter-local helper module instead of expanding the parser boundary.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import spreadsheet_handling.io_backends.xlsx.openpyxl_parser as xp


pytestmark = pytest.mark.ftr("FTR-XLSX-PARSER-MODULARIZATION-P3I")


def test_openpyxl_parser_delegates_visible_sheet_interpretation_to_helper_module():
    module_path = Path(xp.__file__).resolve()
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

    assert "spreadsheet_handling.io_backends.xlsx.parser_interpretation" in imported_modules
    assert "_parse_visible_sheet" in defined_functions
    assert "build_visible_sheet_ir" in called_functions
