"""Guard the domain transformation layer from outer application-facing layers."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.ftr("FTR-DOMAIN-TRANSFORMATION-PACKAGE-BOUNDARY-GUARDS-P5")


REPO_ROOT = Path(__file__).resolve().parents[3]
TRANSFORMATIONS_ROOT = REPO_ROOT / "src" / "spreadsheet_handling" / "domain" / "transformations"

FORBIDDEN_PREFIXES = (
    "spreadsheet_handling.io_backends",
    "spreadsheet_handling.rendering",
    "spreadsheet_handling.cli",
    "spreadsheet_handling.application",
)


def _python_modules(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _path_imports(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def test_domain_transformations_do_not_import_outer_layers() -> None:
    violations: list[str] = []

    for module_path in _python_modules(TRANSFORMATIONS_ROOT):
        module_imports = _path_imports(module_path)
        forbidden = [
            imported
            for imported in module_imports
            if any(
                imported == prefix or imported.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            )
        ]
        if forbidden:
            relative_path = module_path.relative_to(REPO_ROOT)
            joined = ", ".join(sorted(forbidden))
            violations.append(f"{relative_path}: {joined}")

    assert not violations, (
        "domain/transformations must not import outer application-facing layers:\n"
        + "\n".join(violations)
    )
