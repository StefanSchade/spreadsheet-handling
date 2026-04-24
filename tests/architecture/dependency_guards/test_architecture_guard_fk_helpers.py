"""Architecture drift guard: FK-helper domain logic must not live in pipeline.steps.

FTR-FK-HELPER-DOMAIN-EXTRACTION / FTR-ARCHITECTURE-FITNESS-GUARDS-P4X
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

pytestmark = pytest.mark.ftr("FTR-FK-HELPER-DOMAIN-EXTRACTION")

# Symbols that must NOT appear in pipeline.steps because they belong in domain
_FORBIDDEN_IMPORTS = {
    "build_registry",
    "build_id_value_maps",
    "detect_fk_columns",
    "apply_fk_helpers",
}

_FORBIDDEN_PATTERNS = [
    '["derived"]',
    "['derived']",
    '["helper_columns"]',
    "['helper_columns']",
    "._meta",
    '"_meta"',
    "'_meta'",
]


def _steps_source() -> str:
    import spreadsheet_handling.pipeline.steps as mod
    return inspect.getsource(mod)


class TestPipelineStepsHasNoFkHelperDomainLogic:

    def test_no_core_fk_imports(self):
        """pipeline.steps must not import FK-helper core utilities directly."""
        source = _steps_source()
        tree = ast.parse(source)
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
        violations = imported_names & _FORBIDDEN_IMPORTS
        assert not violations, (
            f"pipeline.steps imports FK-helper domain symbols: {violations}. "
            f"These belong in domain.transformations.fk_helpers."
        )

    def test_no_meta_derived_provenance_access(self):
        """pipeline.steps must not manipulate _meta/derived/helper_columns."""
        source = _steps_source()
        violations = [p for p in _FORBIDDEN_PATTERNS if p in source]
        assert not violations, (
            f"pipeline.steps contains _meta/provenance patterns: {violations}. "
            f"Provenance logic belongs in domain.transformations.fk_helpers."
        )
