"""Architecture guard: FK-helper primitives consume policy/provenance only.

``FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5`` removes convention-driven
inference from the FK-helper *primitive* execution path. The primitives
must read either the v2 relation policy under
``_meta.helper_policies.fk`` or the derived helper provenance under
``_meta.derived.sheets.*.helper_columns``.

This guard fails fast if a future change reintroduces ``FK_PATTERN``-based
relation inference or convention-detection helpers
(``detect_fk_columns``, ``build_registry``) into the primitive package or
the ``reorder_helpers_next_to_fk`` primitive. Cell-level parsing utilities
remain free to use ``FK_PATTERN`` for wire-format parsing; this guard only
covers the primitive execution path.
"""
from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.ftr("FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5")


_PRIMITIVE_PACKAGE = "spreadsheet_handling.domain.transformations.fk_helpers"
_REORDER_MODULE = "spreadsheet_handling.domain.transformations.helpers"
_VALIDATION_MODULE = "spreadsheet_handling.domain.validations.fk_helpers"

# Helpers that perform convention-driven FK identity / target detection.
_FORBIDDEN_NAMES = frozenset(
    {
        "detect_fk_columns",
        "build_registry",
        "FK_PATTERN",
    }
)

# Imports allowed for cell-level wire-format parsing / shared helpers.
# ``apply_fk_helpers`` and ``build_id_value_maps`` are deterministic
# materialization helpers that work on already-resolved FKDef rows;
# ``FKDef`` and ``normalize_sheet_key`` are shared structural utilities.
_ALLOWED_CORE_FK_NAMES = frozenset(
    {
        "FKDef",
        "HelperValueProvider",
        "apply_fk_helpers",
        "assert_no_parentheses_in_columns",
        "build_id_label_maps",
        "build_id_sets",
        "build_id_value_maps",
        "normalize_sheet_key",
    }
)


def _iter_primitive_modules() -> list[tuple[str, Path]]:
    pkg = importlib.import_module(_PRIMITIVE_PACKAGE)
    pkg_path = Path(pkg.__file__).resolve().parent
    files = sorted(pkg_path.glob("*.py"))
    return [(f"{_PRIMITIVE_PACKAGE}.{path.stem}", path) for path in files]


def _module_source(module_name: str) -> str:
    mod = importlib.import_module(module_name)
    return inspect.getsource(mod)


def _imported_names_from_core_fk(source: str) -> set[str]:
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if not module.endswith("core.fk"):
            continue
        for alias in node.names:
            imported.add(alias.asname or alias.name)
    return imported


class TestPrimitivesDoNotImportConventionDetection:

    def test_fk_helpers_package_modules_avoid_convention_inference_imports(self):
        for module_name, _path in _iter_primitive_modules():
            source = _module_source(module_name)
            imported = _imported_names_from_core_fk(source)
            violations = imported & _FORBIDDEN_NAMES
            assert not violations, (
                f"{module_name} imports convention-detection helpers from "
                f"core.fk: {violations}. Primitives must consume the v2 "
                f"relation policy or derived helper provenance instead."
            )
            unexpected = imported - _ALLOWED_CORE_FK_NAMES
            assert not unexpected, (
                f"{module_name} imports unexpected names from core.fk: "
                f"{unexpected}. Extend the allowed set deliberately or "
                f"resolve the FK identity through helper_policies/provenance."
            )

    def test_reorder_fk_helpers_step_does_not_import_convention_inference(self):
        source = _module_source(_REORDER_MODULE)
        imported = _imported_names_from_core_fk(source)
        violations = imported & _FORBIDDEN_NAMES
        assert not violations, (
            "reorder_fk_helpers (domain.transformations.helpers) must not "
            f"import convention-detection helpers from core.fk: {violations}. "
            "Helper placement is driven by v2 policy or derived helper provenance."
        )

    def test_validate_fk_helpers_does_not_import_convention_inference(self):
        source = _module_source(_VALIDATION_MODULE)
        imported = _imported_names_from_core_fk(source)
        violations = imported & _FORBIDDEN_NAMES
        assert not violations, (
            "domain.validations.fk_helpers imports convention-detection "
            f"helpers from core.fk: {violations}. Validation primitives "
            "must consume v2 policy / provenance instead."
        )


class TestEnrichHelpersDoesNotCallDetectFkColumns:

    def test_enrich_module_text_does_not_reference_detect_fk_columns(self):
        from spreadsheet_handling.domain.transformations.fk_helpers import (
            enrich,
        )
        source = inspect.getsource(enrich)
        assert "detect_fk_columns" not in source, (
            "enrich_helpers must not invoke detect_fk_columns; "
            "FK identity comes from helper_policies.fk (v2) only."
        )
        assert "FK_PATTERN" not in source, (
            "enrich_helpers must not consult FK_PATTERN for relation "
            "inference inside the primitive."
        )


class TestPrimitivesReadV2PolicyOrProvenance:
    """Each primitive must reference one of the policy / provenance roots.

    The check is intentionally textual: if a future refactor removes both
    references, the primitive can no longer be reading the policy or
    provenance and almost certainly slid back into convention detection.
    """

    POLICY_TOKENS = (
        "helper_policies",
        "resolve_v2_fk_relations",
        "derived_helper_columns_by_sheet",
        "derived",
    )

    def _assert_module_reads_policy_or_provenance(self, module_name: str) -> None:
        source = _module_source(module_name)
        assert any(token in source for token in self.POLICY_TOKENS), (
            f"{module_name} must read FK structure from helper_policies "
            "(v2) or derived helper provenance."
        )

    def test_enrich_helpers_reads_v2_policy(self):
        self._assert_module_reads_policy_or_provenance(
            f"{_PRIMITIVE_PACKAGE}.enrich"
        )

    def test_drop_helpers_reads_provenance_or_policy(self):
        self._assert_module_reads_policy_or_provenance(
            f"{_PRIMITIVE_PACKAGE}.drop"
        )

    def test_reorder_fk_helpers_reads_provenance_or_policy(self):
        self._assert_module_reads_policy_or_provenance(_REORDER_MODULE)

    def test_validate_fk_helpers_reads_provenance_or_policy(self):
        self._assert_module_reads_policy_or_provenance(_VALIDATION_MODULE)
