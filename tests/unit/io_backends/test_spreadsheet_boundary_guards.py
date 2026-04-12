from __future__ import annotations

"""Conservative architectural seam guards for spreadsheet-capable backends.

These checks intentionally cover the most important spreadsheet boundary modules
and adapter entry points. They are not a full repository-wide architecture
linter, but a focused drift-protection layer for the seams that Phase 3i wants
to keep narrow. The rendering-tree guard also encodes the current policy that
`spreadsheet_handling.rendering` stays adapter-free and generic.
"""

import ast
from pathlib import Path

import pytest

import spreadsheet_handling.io_backends._interfaces as interfaces_mod
import spreadsheet_handling.io_backends.spreadsheet_contract as contract_mod
import spreadsheet_handling.io_backends.xlsx.openpyxl_parser as parser_mod
import spreadsheet_handling.io_backends.xlsx.openpyxl_renderer as renderer_mod
import spreadsheet_handling.io_backends.xlsx.parser_interpretation as interpretation_mod
import spreadsheet_handling.io_backends.xlsx.xlsx_backend as backend_mod
import spreadsheet_handling.rendering as rendering_pkg


pytestmark = pytest.mark.ftr("FTR-SPREADSHEET-BOUNDARY-GUARDS-P3I")


def _path_imports(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def _module_imports(module) -> list[str]:
    return _path_imports(Path(module.__file__).resolve())


def _assert_no_import_prefixes(module_path: Path, *, forbidden_prefixes: tuple[str, ...]) -> None:
    imports = _path_imports(module_path)
    violations = [
        name for name in imports
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
    ]
    assert not violations, (
        f"{module_path.name} violates spreadsheet boundary guards:\n" + "\n".join(sorted(violations))
    )


def test_generic_spreadsheet_modules_stay_free_of_xlsx_and_openpyxl_dependencies():
    root = Path(rendering_pkg.__file__).resolve().parent
    generic_modules = sorted(root.rglob("*.py"))
    generic_modules.extend(
        [
            Path(contract_mod.__file__).resolve(),
            Path(interfaces_mod.__file__).resolve(),
        ]
    )

    forbidden_prefixes = (
        "openpyxl",
        "spreadsheet_handling.io_backends.xlsx",
    )

    for module_path in generic_modules:
        _assert_no_import_prefixes(module_path, forbidden_prefixes=forbidden_prefixes)


def test_xlsx_backend_imports_generic_code_through_spreadsheet_contract_boundary():
    imports = _module_imports(backend_mod)

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


def test_xlsx_parser_stops_at_workbook_ir_boundary():
    imports = _module_imports(parser_mod)

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


def test_xlsx_parser_interpretation_stays_out_of_projection_and_contract_layers():
    imports = _module_imports(interpretation_mod)

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
    imports = _module_imports(renderer_mod)

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
