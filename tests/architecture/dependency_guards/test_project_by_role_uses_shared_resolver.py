"""Architecture guard: project_by_role must consume the shared resolver.

`FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5` requires a single source of truth
for column-role detection so that `project_by_role` and the future
targeting implementation slice cannot diverge. This guard fails loudly
if `project_by_role` reimplements role detection instead of calling
`spreadsheet_handling.domain.column_roles.resolve_column_roles`.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.ftr("FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5")


REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_BY_ROLE_PATH = (
    REPO_ROOT
    / "src"
    / "spreadsheet_handling"
    / "domain"
    / "transformations"
    / "project_by_role.py"
)


def _read_module_ast() -> ast.Module:
    with PROJECT_BY_ROLE_PATH.open("r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=str(PROJECT_BY_ROLE_PATH))


def test_project_by_role_imports_shared_resolver() -> None:
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
        "project_by_role.py must import resolve_column_roles from "
        "spreadsheet_handling.domain.column_roles; see "
        "FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5 (shared-resolver guard)."
    )


def test_project_by_role_calls_shared_resolver() -> None:
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
        "project_by_role.py must call resolve_column_roles for role detection; "
        "FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5 forbids parallel role-detection logic."
    )


def test_project_by_role_does_not_redefine_role_constants() -> None:
    """Guard against introducing a parallel role vocabulary in the step file.

    The step is allowed to reference the foundation role names by importing
    them from the shared resolver, but defining new top-level string
    constants whose values are the role names would silently fork the
    vocabulary.
    """
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
        "project_by_role.py defines string constants whose value is a "
        f"foundation role name ({forbidden_definitions!r}); import the role "
        "names from spreadsheet_handling.domain.column_roles instead."
    )
