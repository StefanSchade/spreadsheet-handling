"""Guard against cross-family imports into transformation implementation modules.

Package-split transformation families may import local siblings, but other
transformation code must not couple to another family's private submodules.
"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

pytestmark = pytest.mark.ftr("FTR-DOMAIN-TRANSFORMATION-PACKAGE-BOUNDARY-GUARDS-P5")


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
TRANSFORMATIONS_ROOT = SRC_ROOT / "spreadsheet_handling" / "domain" / "transformations"

GUARDED_INTERNAL_PREFIXES = {
    "spreadsheet_handling.domain.transformations.fk_helpers": (
        "spreadsheet_handling.domain.transformations.fk_helpers.drop",
        "spreadsheet_handling.domain.transformations.fk_helpers.enrich",
        "spreadsheet_handling.domain.transformations.fk_helpers.formula_provider",
        "spreadsheet_handling.domain.transformations.fk_helpers.policy",
        "spreadsheet_handling.domain.transformations.fk_helpers.provenance",
    ),
    "spreadsheet_handling.domain.transformations.discriminator_split": (
        "spreadsheet_handling.domain.transformations.discriminator_split.framecheck",
        "spreadsheet_handling.domain.transformations.discriminator_split.merge",
        "spreadsheet_handling.domain.transformations.discriminator_split.metadata",
        "spreadsheet_handling.domain.transformations.discriminator_split.naming",
        "spreadsheet_handling.domain.transformations.discriminator_split.split",
        "spreadsheet_handling.domain.transformations.discriminator_split.values",
    ),
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


def test_transformations_do_not_import_other_families_internal_modules() -> None:
    violations: list[str] = []

    for module_path in _python_modules(TRANSFORMATIONS_ROOT):
        importer = _module_name(module_path)
        imports = _resolved_imports(module_path)

        for family_root, internal_prefixes in GUARDED_INTERNAL_PREFIXES.items():
            if importer == family_root or importer.startswith(family_root + "."):
                continue

            for imported in imports:
                if imported in internal_prefixes:
                    violations.append(
                        f"{importer} imports {imported}; "
                        f"cross-family access must go through {family_root} only."
                    )

    assert not violations, "Cross-family transformation import violations:\n" + "\n".join(violations)
