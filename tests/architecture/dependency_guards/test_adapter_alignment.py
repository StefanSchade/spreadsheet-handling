"""Dependency guards for the XLSX adapter alignment seam.

These checks keep the generic rendering package and spreadsheet contract free
of direct XLSX implementation leakage while confirming the XLSX parser owns its
backend-specific read path locally.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import spreadsheet_handling.io_backends.spreadsheet_contract as sc
import spreadsheet_handling.io_backends.xlsx.openpyxl_parser as xp
import spreadsheet_handling.rendering as rendering_pkg


pytestmark = pytest.mark.ftr("FTR-XLSX-ADAPTER-ALIGNMENT-P3H")


def _module_imports(module) -> list[str]:
    module_path = Path(module.__file__).resolve()
    return _path_imports(module_path)


def _path_imports(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def test_openpyxl_parser_owns_xlsx_readpath_locally():
    imports = _module_imports(xp)

    assert "spreadsheet_handling.rendering.parse_ir" not in imports
    assert any(name == "openpyxl" or name.startswith("openpyxl.") for name in imports)


def test_spreadsheet_contract_uses_generic_workbook_projection_only():
    imports = _module_imports(sc)

    assert "spreadsheet_handling.rendering.workbook_projection" in imports
    assert not any(name.startswith("spreadsheet_handling.io_backends.xlsx") for name in imports)


def test_generic_rendering_package_stays_free_of_openpyxl_and_xlsx_adapter_imports():
    rendering_root = Path(rendering_pkg.__file__).resolve().parent

    for module_path in rendering_root.rglob("*.py"):
        imports = _path_imports(module_path)
        assert not any(name == "openpyxl" or name.startswith("openpyxl.") for name in imports), module_path
        assert not any(
            name.startswith("spreadsheet_handling.io_backends.xlsx") for name in imports
        ), module_path
