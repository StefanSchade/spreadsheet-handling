"""Adapter contract boundary guards for concrete spreadsheet backends.

These checks keep XLSX and ODS adapters narrow: backend entry points delegate
generic orchestration to the spreadsheet contract facade, concrete renderers
consume ``RenderPlan``, and parsers stop at ``WorkbookIR``.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.ftr("FTR-ADAPTER-CONTRACT-BOUNDARY-GUARDS-P4")


REPO_ROOT = Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "src" / "spreadsheet_handling"
IO_BACKENDS_ROOT = PKG_ROOT / "io_backends"

CONTRACT_PATH = IO_BACKENDS_ROOT / "spreadsheet_contract.py"

BACKEND_ENTRYPOINTS = (
    IO_BACKENDS_ROOT / "xlsx" / "xlsx_backend.py",
    IO_BACKENDS_ROOT / "ods" / "ods_backend.py",
)
RENDERERS = (
    IO_BACKENDS_ROOT / "xlsx" / "openpyxl_renderer.py",
    IO_BACKENDS_ROOT / "ods" / "odf_renderer.py",
)
PARSERS = (
    (
        IO_BACKENDS_ROOT / "xlsx" / "openpyxl_parser.py",
        "spreadsheet_handling.io_backends.xlsx.parser_interpretation",
    ),
    (
        IO_BACKENDS_ROOT / "ods" / "odf_parser.py",
        "spreadsheet_handling.io_backends.ods.parser_interpretation",
    ),
)
PARSER_INTERPRETATION_MODULES = (
    IO_BACKENDS_ROOT / "xlsx" / "parser_interpretation.py",
    IO_BACKENDS_ROOT / "ods" / "parser_interpretation.py",
)


def _path_imports(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")

    return imports


def _violating_imports(imports: list[str], forbidden_prefixes: tuple[str, ...]) -> list[str]:
    return sorted(
        {
            name
            for name in imports
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
        }
    )


def _assert_no_forbidden_imports(module_path: Path, forbidden_prefixes: tuple[str, ...]) -> None:
    violations = _violating_imports(_path_imports(module_path), forbidden_prefixes)
    rel_path = module_path.relative_to(REPO_ROOT).as_posix()
    assert not violations, f"{rel_path} crosses adapter contract boundaries:\n" + "\n".join(violations)


def test_backend_entrypoints_delegate_generic_orchestration_to_spreadsheet_contract():
    forbidden_prefixes = (
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.plan",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.ir",
        "spreadsheet_handling.domain",
        "spreadsheet_handling.pipeline",
    )

    for module_path in BACKEND_ENTRYPOINTS:
        imports = _path_imports(module_path)
        assert "spreadsheet_handling.io_backends.spreadsheet_contract" in imports
        _assert_no_forbidden_imports(module_path, forbidden_prefixes)


def test_concrete_renderers_consume_render_plan_without_reaching_back():
    forbidden_prefixes = (
        "spreadsheet_handling.io_backends.spreadsheet_contract",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.ir",
        "spreadsheet_handling.domain",
        "spreadsheet_handling.pipeline",
    )

    for module_path in RENDERERS:
        imports = _path_imports(module_path)
        assert "spreadsheet_handling.rendering.plan" in imports
        _assert_no_forbidden_imports(module_path, forbidden_prefixes)


def test_concrete_parsers_stop_at_workbook_ir_and_local_interpretation():
    forbidden_prefixes = (
        "spreadsheet_handling.io_backends.spreadsheet_contract",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.plan",
        "spreadsheet_handling.domain",
        "spreadsheet_handling.pipeline",
    )

    for module_path, local_interpretation_import in PARSERS:
        imports = _path_imports(module_path)
        assert "spreadsheet_handling.rendering.ir" in imports
        assert local_interpretation_import in imports
        _assert_no_forbidden_imports(module_path, forbidden_prefixes)


def test_parser_interpretation_modules_stay_parser_local():
    forbidden_prefixes = (
        "spreadsheet_handling.io_backends.spreadsheet_contract",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.plan",
        "spreadsheet_handling.domain",
        "spreadsheet_handling.pipeline",
    )

    for module_path in PARSER_INTERPRETATION_MODULES:
        imports = _path_imports(module_path)
        assert "spreadsheet_handling.rendering.ir" in imports
        _assert_no_forbidden_imports(module_path, forbidden_prefixes)


def test_spreadsheet_contract_facade_stays_backend_neutral():
    imports = _path_imports(CONTRACT_PATH)
    forbidden_prefixes = (
        "openpyxl",
        "odf",
        "spreadsheet_handling.io_backends.xlsx",
        "spreadsheet_handling.io_backends.ods",
    )

    assert "spreadsheet_handling.rendering.workbook_projection" in imports
    assert "spreadsheet_handling.rendering.plan" in imports
    _assert_no_forbidden_imports(CONTRACT_PATH, forbidden_prefixes)
