"""Guard the domain transformation layer from outer application-facing layers."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

pytestmark = pytest.mark.ftr("FTR-DOMAIN-TRANSFORMATION-PACKAGE-BOUNDARY-GUARDS-P5")


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
TRANSFORMATIONS_ROOT = SRC_ROOT / "spreadsheet_handling" / "domain" / "transformations"

FORBIDDEN_PREFIXES = (
    "spreadsheet_handling.io_backends",
    "spreadsheet_handling.rendering",
    "spreadsheet_handling.cli",
    "spreadsheet_handling.application",
)


def _python_modules(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _module_name(module_path: Path) -> str:
    relative = module_path.relative_to(SRC_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_context(module_name: str, module_path: Path) -> str:
    return module_name if module_path.name == "__init__.py" else module_name.rsplit(".", 1)[0]


def _resolved_imports(module_path: Path) -> list[str]:
    module_name = _module_name(module_path)
    package_context = _package_context(module_name, module_path)
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            relative_name = "." * node.level + (node.module or "")
            imports.append(resolve_name(relative_name, package_context))
    return imports


def test_domain_transformations_do_not_import_outer_layers() -> None:
    violations: list[str] = []

    for module_path in _python_modules(TRANSFORMATIONS_ROOT):
        module_imports = _resolved_imports(module_path)
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
