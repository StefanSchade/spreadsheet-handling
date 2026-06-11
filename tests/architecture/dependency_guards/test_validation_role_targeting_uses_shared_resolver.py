"""Architecture guard: validation role targeting must use the shared resolver."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.ftr("FTR-DYNAMIC-VIEW-COLUMN-TARGETING-IMPL-P5")


REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATE_COLUMNS_PATH = (
    REPO_ROOT
    / "src"
    / "spreadsheet_handling"
    / "domain"
    / "validations"
    / "validate_columns.py"
)


def _read_module_ast() -> ast.Module:
    with VALIDATE_COLUMNS_PATH.open("r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=str(VALIDATE_COLUMNS_PATH))


def test_add_validations_imports_shared_resolver() -> None:
    module = _read_module_ast()

    imports_resolver = False
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            if node.module == "spreadsheet_handling.domain.column_roles" and any(
                alias.name == "resolve_column_roles" for alias in node.names
            ):
                imports_resolver = True
                break

    assert imports_resolver, (
        "validate_columns.py must import resolve_column_roles from "
        "spreadsheet_handling.domain.column_roles for role-target expansion."
    )


def test_add_validations_calls_shared_resolver() -> None:
    module = _read_module_ast()

    calls_resolver = False
    for node in ast.walk(module):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "resolve_column_roles":
                calls_resolver = True
                break
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "resolve_column_roles"
            ):
                calls_resolver = True
                break

    assert calls_resolver, (
        "validate_columns.py must call resolve_column_roles for role-target "
        "expansion; FTR-DYNAMIC-VIEW-COLUMN-TARGETING-IMPL-P5 forbids "
        "parallel role-detection logic."
    )


def test_add_validations_does_not_redefine_role_constants() -> None:
    module = _read_module_ast()
    forbidden_definitions: list[str] = []
    role_values = {"row_identity", "display_helper", "matrix_value"}

    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        if node.value.value not in role_values:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                forbidden_definitions.append(target.id)

    assert not forbidden_definitions, (
        "validate_columns.py defines string constants whose value is a "
        f"foundation role name ({forbidden_definitions!r}); import role "
        "names from spreadsheet_handling.domain.column_roles instead."
    )
