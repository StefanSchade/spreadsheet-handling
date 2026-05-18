"""Guard package-root public APIs for modularized transformation families.

External production imports must use the package root for the guarded
transformation families. Internal sibling imports remain allowed inside the
same family package.
"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

pytestmark = pytest.mark.ftr("FTR-DOMAIN-TRANSFORMATION-PACKAGE-BOUNDARY-GUARDS-P5")


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
PKG_ROOT = SRC_ROOT / "spreadsheet_handling"

GUARDED_FAMILIES = {
    "spreadsheet_handling.domain.transformations.fk_helpers": {
        "spreadsheet_handling.domain.transformations.fk_helpers.drop",
        "spreadsheet_handling.domain.transformations.fk_helpers.enrich",
        "spreadsheet_handling.domain.transformations.fk_helpers.formula_provider",
        "spreadsheet_handling.domain.transformations.fk_helpers.policy",
        "spreadsheet_handling.domain.transformations.fk_helpers.provenance",
    },
    "spreadsheet_handling.domain.transformations.discriminator_split": {
        "spreadsheet_handling.domain.transformations.discriminator_split.framecheck",
        "spreadsheet_handling.domain.transformations.discriminator_split.merge",
        "spreadsheet_handling.domain.transformations.discriminator_split.metadata",
        "spreadsheet_handling.domain.transformations.discriminator_split.naming",
        "spreadsheet_handling.domain.transformations.discriminator_split.split",
        "spreadsheet_handling.domain.transformations.discriminator_split.values",
    },
}


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


def test_external_imports_use_guarded_package_roots() -> None:
    violations: list[str] = []

    for module_path in _python_modules(PKG_ROOT):
        importer = _module_name(module_path)
        imports = _resolved_imports(module_path)

        for family_root, internal_modules in GUARDED_FAMILIES.items():
            if importer == family_root or importer.startswith(family_root + "."):
                continue

            for imported in imports:
                if imported in internal_modules:
                    violations.append(
                        f"{importer} imports internal module {imported}; "
                        f"use {family_root} package root instead."
                    )

    assert not violations, "Guarded transformation public API violations:\n" + "\n".join(violations)
