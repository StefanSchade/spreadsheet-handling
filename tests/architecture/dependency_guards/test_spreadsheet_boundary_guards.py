"""Conservative architectural seam guards for spreadsheet-capable backends.

These checks intentionally cover the most important spreadsheet boundary modules
and adapter entry points. They are not a full repository-wide architecture
linter, but a focused drift-protection layer for the seams that Phase 3i wants
to keep narrow. The rendering-tree guard also encodes the current policy that
`spreadsheet_handling.rendering` stays adapter-free and generic.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.ftr("FTR-SPREADSHEET-BOUNDARY-GUARDS-P3I"),
    pytest.mark.ftr("FTR-ARCHITECTURE-FITNESS-GUARDS-P4X"),
]


REPO_ROOT = Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "src" / "spreadsheet_handling"
RENDERING_ROOT = PKG_ROOT / "rendering"
DOMAIN_ROOT = PKG_ROOT / "domain"
CORE_ROOT = PKG_ROOT / "core"
PIPELINE_ROOT = PKG_ROOT / "pipeline"
IO_BACKENDS_ROOT = PKG_ROOT / "io_backends"

CONTRACT_PATH = IO_BACKENDS_ROOT / "spreadsheet_contract.py"
INTERFACES_PATH = IO_BACKENDS_ROOT / "_interfaces.py"
XLSX_BACKEND_PATH = IO_BACKENDS_ROOT / "xlsx" / "xlsx_backend.py"
XLSX_PARSER_PATH = IO_BACKENDS_ROOT / "xlsx" / "openpyxl_parser.py"
XLSX_INTERPRETATION_PATH = IO_BACKENDS_ROOT / "xlsx" / "parser_interpretation.py"
XLSX_RENDERER_PATH = IO_BACKENDS_ROOT / "xlsx" / "openpyxl_renderer.py"
ODS_BACKEND_PATH = IO_BACKENDS_ROOT / "ods" / "ods_backend.py"
ODS_PARSER_PATH = IO_BACKENDS_ROOT / "ods" / "odf_parser.py"
ODS_INTERPRETATION_PATH = IO_BACKENDS_ROOT / "ods" / "parser_interpretation.py"
ODS_RENDERER_PATH = IO_BACKENDS_ROOT / "ods" / "odf_renderer.py"


def _path_imports(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def _assert_no_import_prefixes(module_path: Path, *, forbidden_prefixes: tuple[str, ...]) -> None:
    imports = _path_imports(module_path)
    violations = [
        name for name in imports
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
    ]
    assert not violations, (
        f"{module_path.name} violates spreadsheet boundary guards:\n" + "\n".join(sorted(violations))
    )


def _package_modules(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_generic_spreadsheet_modules_stay_free_of_xlsx_and_openpyxl_dependencies():
    generic_modules = _package_modules(RENDERING_ROOT)
    generic_modules.extend([CONTRACT_PATH, INTERFACES_PATH])

    forbidden_prefixes = (
        "openpyxl",
        "odf",
        "spreadsheet_handling.io_backends.ods",
        "spreadsheet_handling.io_backends.xlsx",
    )

    for module_path in generic_modules:
        _assert_no_import_prefixes(module_path, forbidden_prefixes=forbidden_prefixes)


def test_xlsx_backend_imports_generic_code_through_spreadsheet_contract_boundary():
    imports = _path_imports(XLSX_BACKEND_PATH)

    assert "spreadsheet_handling.io_backends.spreadsheet_contract" in imports

    forbidden_prefixes = (
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.plan",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.ir",
    )
    violations = [
        name for name in imports
        if any(name.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "xlsx_backend.py must keep generic imports on the spreadsheet contract boundary:\n"
        + "\n".join(sorted(violations))
    )


def test_ods_backend_imports_generic_code_through_spreadsheet_contract_boundary():
    imports = _path_imports(ODS_BACKEND_PATH)

    assert "spreadsheet_handling.io_backends.spreadsheet_contract" in imports

    forbidden_prefixes = (
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.plan",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.ir",
    )
    violations = [
        name for name in imports
        if any(name.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "ods_backend.py must keep generic imports on the spreadsheet contract boundary:\n"
        + "\n".join(sorted(violations))
    )


def test_xlsx_parser_stops_at_workbook_ir_boundary():
    imports = _path_imports(XLSX_PARSER_PATH)

    assert "spreadsheet_handling.rendering.ir" in imports
    assert "spreadsheet_handling.io_backends.xlsx.parser_interpretation" in imports

    forbidden_prefixes = (
        "spreadsheet_handling.io_backends.spreadsheet_contract",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.plan",
    )
    violations = [
        name for name in imports
        if any(name.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "openpyxl_parser.py must stop at WorkbookIR and not reach through to other boundaries:\n"
        + "\n".join(sorted(violations))
    )


def test_ods_parser_stops_at_workbook_ir_boundary():
    imports = _path_imports(ODS_PARSER_PATH)

    assert "spreadsheet_handling.rendering.ir" in imports
    assert "spreadsheet_handling.io_backends.ods.parser_interpretation" in imports

    forbidden_prefixes = (
        "spreadsheet_handling.io_backends.spreadsheet_contract",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.plan",
    )
    violations = [
        name for name in imports
        if any(name.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "odf_parser.py must stop at WorkbookIR and not reach through to other boundaries:\n"
        + "\n".join(sorted(violations))
    )


def test_ods_parser_interpretation_stays_out_of_projection_and_contract_layers():
    imports = _path_imports(ODS_INTERPRETATION_PATH)

    assert "spreadsheet_handling.rendering.ir" in imports

    forbidden_prefixes = (
        "spreadsheet_handling.io_backends.spreadsheet_contract",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.plan",
    )
    violations = [
        name for name in imports
        if any(name.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "ods/parser_interpretation.py must stay on the parser-side interpretation boundary:\n"
        + "\n".join(sorted(violations))
    )


def test_xlsx_parser_interpretation_stays_out_of_projection_and_contract_layers():
    imports = _path_imports(XLSX_INTERPRETATION_PATH)

    assert "spreadsheet_handling.rendering.ir" in imports

    forbidden_prefixes = (
        "spreadsheet_handling.io_backends.spreadsheet_contract",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.plan",
    )
    violations = [
        name for name in imports
        if any(name.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "parser_interpretation.py must stay on the parser-side interpretation boundary:\n"
        + "\n".join(sorted(violations))
    )


def test_xlsx_renderer_consumes_render_plan_without_reaching_back_into_rendering_pipeline():
    imports = _path_imports(XLSX_RENDERER_PATH)

    assert "spreadsheet_handling.rendering.plan" in imports

    forbidden_prefixes = (
        "spreadsheet_handling.io_backends.spreadsheet_contract",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.ir",
    )
    violations = [
        name for name in imports
        if any(name.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "openpyxl_renderer.py must consume RenderPlan without reaching back into earlier layers:\n"
        + "\n".join(sorted(violations))
    )


def test_ods_renderer_consumes_render_plan_without_reaching_back_into_rendering_pipeline():
    imports = _path_imports(ODS_RENDERER_PATH)

    assert "spreadsheet_handling.rendering.plan" in imports

    forbidden_prefixes = (
        "spreadsheet_handling.io_backends.spreadsheet_contract",
        "spreadsheet_handling.rendering.workbook_projection",
        "spreadsheet_handling.rendering.composer",
        "spreadsheet_handling.rendering.passes",
        "spreadsheet_handling.rendering.flow",
        "spreadsheet_handling.rendering.ir",
    )
    violations = [
        name for name in imports
        if any(name.startswith(prefix) for prefix in forbidden_prefixes)
    ]

    assert not violations, (
        "odf_renderer.py must consume RenderPlan without reaching back into earlier layers:\n"
        + "\n".join(sorted(violations))
    )


def test_domain_modules_do_not_import_pipeline_layer():
    forbidden_prefixes = ("spreadsheet_handling.pipeline",)

    for module_path in _package_modules(DOMAIN_ROOT):
        _assert_no_import_prefixes(module_path, forbidden_prefixes=forbidden_prefixes)


def test_core_modules_remain_leaf_only():
    forbidden_prefixes = (
        "spreadsheet_handling.domain",
        "spreadsheet_handling.pipeline",
        "spreadsheet_handling.rendering",
        "spreadsheet_handling.io_backends",
    )

    for module_path in _package_modules(CORE_ROOT):
        _assert_no_import_prefixes(module_path, forbidden_prefixes=forbidden_prefixes)


def test_pipeline_runner_and_registry_stay_out_of_payload_semantics():
    forbidden_patterns = (
        '"_meta"',
        "'_meta'",
        '["derived"]',
        "['derived']",
        '["helper_columns"]',
        "['helper_columns']",
    )
    checked_modules = [
        PIPELINE_ROOT / "pipeline.py",
        PIPELINE_ROOT / "registry.py",
    ]

    for module_path in checked_modules:
        source = module_path.read_text(encoding="utf-8")
        violations = [pattern for pattern in forbidden_patterns if pattern in source]
        assert not violations, (
            f"{module_path.name} inspects payload semantics that should stay in domain: "
            + ", ".join(violations)
        )
