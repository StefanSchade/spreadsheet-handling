"""Guard against cross-family imports into transformation implementation modules.

Package-split transformation families may import local siblings, but other
transformation code must not couple to another family's private submodules.
"""

from __future__ import annotations

import ast
import sys
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
    "spreadsheet_handling.domain.transformations.enrich_lookup": (
        "spreadsheet_handling.domain.transformations.enrich_lookup.mismatch",
        "spreadsheet_handling.domain.transformations.enrich_lookup.operation",
        "spreadsheet_handling.domain.transformations.enrich_lookup.policy",
        "spreadsheet_handling.domain.transformations.enrich_lookup.provenance",
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
            resolved_module = resolve_name(relative_name, package_context)
            imports.append(resolved_module)
            # `from <family-package> import <internal-module>` (e.g.
            # `from enrich_lookup import provenance`) imports an internal
            # module by its bare name rather than a facade symbol. The
            # imported *name* (not the local alias) may itself be that
            # submodule, so consider the qualified candidate too -- otherwise
            # only the family-package import above is checked and the
            # internal-module import bypasses the guard (IMPL-REV-001).
            imports.extend(
                f"{resolved_module}.{alias.name}" for alias in node.names
            )
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


# ---------------------------------------------------------------------------
# Regression coverage for IMPL-REV-001: `from <family> import <internal>`
# previously resolved only to the family package, not the qualified internal
# module, and so bypassed the guard above. These tests exercise
# `_resolved_imports` directly against a throwaway module written under a
# fake `SRC_ROOT` that mirrors the real package layout, since `_module_name`
# resolves paths relative to `SRC_ROOT`.
# ---------------------------------------------------------------------------

_ENRICH_LOOKUP_ROOT = "spreadsheet_handling.domain.transformations.enrich_lookup"
_ENRICH_LOOKUP_INTERNAL_PREFIXES = GUARDED_INTERNAL_PREFIXES[_ENRICH_LOOKUP_ROOT]


def _write_fake_consumer(tmp_path: Path, import_statement: str) -> Path:
    """Write a throwaway consumer module under a fake ``SRC_ROOT``.

    The fake root mirrors the real ``transformations`` package layout so
    ``_resolved_imports`` resolves the import exactly as it would for real
    repository code.
    """
    module_path = (
        tmp_path
        / "src"
        / "spreadsheet_handling"
        / "domain"
        / "transformations"
        / "consumer_family"
        / "consumer.py"
    )
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(import_statement + "\n")
    return module_path


def _resolved_imports_with_fake_src_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, import_statement: str,
) -> list[str]:
    module_path = _write_fake_consumer(tmp_path, import_statement)
    monkeypatch.setattr(sys.modules[__name__], "SRC_ROOT", tmp_path / "src")
    return _resolved_imports(module_path)


@pytest.mark.parametrize("internal_module", ["operation", "policy", "provenance"])
def test_bare_name_import_of_internal_module_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, internal_module: str,
) -> None:
    """``from <family> import <internal-module>`` must resolve to the
    qualified internal-module path, closing the IMPL-REV-001 bypass."""
    resolved = _resolved_imports_with_fake_src_root(
        tmp_path, monkeypatch, f"from {_ENRICH_LOOKUP_ROOT} import {internal_module}",
    )
    expected = f"{_ENRICH_LOOKUP_ROOT}.{internal_module}"
    assert expected in resolved
    assert any(candidate in _ENRICH_LOOKUP_INTERNAL_PREFIXES for candidate in resolved)


def test_aliased_bare_name_import_of_internal_module_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard reasons from the imported name, not the local alias."""
    resolved = _resolved_imports_with_fake_src_root(
        tmp_path, monkeypatch,
        f"from {_ENRICH_LOOKUP_ROOT} import provenance as p",
    )
    assert f"{_ENRICH_LOOKUP_ROOT}.provenance" in resolved
    assert any(candidate in _ENRICH_LOOKUP_INTERNAL_PREFIXES for candidate in resolved)


def test_facade_symbol_import_remains_permitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The H5-slice facade import must not be flagged as an internal module."""
    resolved = _resolved_imports_with_fake_src_root(
        tmp_path, monkeypatch,
        f"from {_ENRICH_LOOKUP_ROOT} import reconcile_enrich_lookup_provenance",
    )
    assert not any(candidate in _ENRICH_LOOKUP_INTERNAL_PREFIXES for candidate in resolved)
