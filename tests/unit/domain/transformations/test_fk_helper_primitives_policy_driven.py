"""Focused tests for FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5.

These tests pin the FTR's acceptance criteria for the v2-aware primitive
behavior: explicit policy path, inferred policy path, missing-policy errors,
provenance-driven cleanup, and helper validation through ``target_key``.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.fk_relations import infer_fk_relations
from spreadsheet_handling.domain.helper_policies import configure_fk_helpers
from spreadsheet_handling.domain.transformations.fk_helpers import (
    drop_helpers,
    enrich_helpers,
)
from spreadsheet_handling.domain.transformations.helpers import (
    reorder_helpers_next_to_fk,
)
from spreadsheet_handling.domain.validations.fk_helpers import (
    check_helper_values,
    check_missing_helpers,
    check_unresolvable_fks,
)

pytestmark = pytest.mark.ftr("FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5")


def _orders_and_products() -> dict:
    return {
        "orders": pd.DataFrame(
            {
                "order_id": ["o1", "o2"],
                "code_(products)": ["p1", "p2"],
            }
        ),
        "products": pd.DataFrame(
            {
                "code": ["p1", "p2"],
                "name": ["Alpha", "Beta"],
                "category": ["A", "B"],
            }
        ),
    }


# ---------------------------------------------------------------------------
# Acceptance: explicit policy path
# ---------------------------------------------------------------------------

class TestExplicitPolicyPath:

    def test_configure_then_add_materializes_declared_helpers(self):
        configured = configure_fk_helpers(
            _orders_and_products(),
            target="products",
            key="code",
            allowed_helpers=["name", "category"],
            default_helpers=["category", "name"],
        )

        out = enrich_helpers(configured, {})

        lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["orders"].columns]
        assert "_products_category" in lvl0
        assert "_products_name" in lvl0

    def test_provenance_carries_target_key_from_policy(self):
        configured = configure_fk_helpers(
            _orders_and_products(),
            target="products",
            key="code",
            allowed_helpers=["name"],
            default_helpers=["name"],
        )

        out = enrich_helpers(configured, {})
        prov = out["_meta"]["derived"]["sheets"]["orders"]["helper_columns"]
        assert prov == [
            {
                "column": "_products_name",
                "fk_column": "code_(products)",
                "target": "products",
                "target_key": "code",
                "value_field": "name",
            }
        ]


# ---------------------------------------------------------------------------
# Acceptance: inferred policy path
# ---------------------------------------------------------------------------

class TestInferredPolicyPath:

    def test_infer_then_add_uses_v2_relations_from_inference(self):
        inferred = infer_fk_relations(
            _orders_and_products(),
            id_columns=["code"],
            fk_patterns=["code_({target})"],
        )

        out = enrich_helpers(inferred, {})

        lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["orders"].columns]
        assert "_products_name" in lvl0
        prov = out["_meta"]["derived"]["sheets"]["orders"]["helper_columns"]
        assert prov[0]["target_key"] == "code"


# ---------------------------------------------------------------------------
# Acceptance: missing policy errors
# ---------------------------------------------------------------------------

class TestMissingPolicyErrors:

    def test_add_fk_helpers_without_policy_raises(self):
        with pytest.raises(ValueError, match="configure_fk_helpers"):
            enrich_helpers(_orders_and_products(), {})

    def test_add_fk_helpers_error_names_inference_step(self):
        with pytest.raises(ValueError, match="infer_fk_relations"):
            enrich_helpers(_orders_and_products(), {})

    def test_remove_fk_helpers_without_policy_or_provenance_raises(self):
        with pytest.raises(ValueError, match="infer_fk_relations"):
            drop_helpers(_orders_and_products())

    def test_reorder_without_policy_or_provenance_raises(self):
        step = reorder_helpers_next_to_fk()
        with pytest.raises(ValueError, match="infer_fk_relations"):
            step(_orders_and_products())

    def test_v1_only_policy_is_not_consumed_by_primitives(self):
        """A persisted v1-shape policy without ``schema_version: 2`` must
        not be silently consumed by primitives.
        """
        frames = _orders_and_products()
        frames["_meta"] = {
            "helper_policies": {
                "fk": {
                    "products": {
                        "target": "products",
                        "target_sheet": "products",
                        "key": "code",
                        "allowed_helpers": ["name"],
                        "default_helpers": ["name"],
                        "helper_prefix": "_",
                        "fk_column": "code_(products)",
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="schema_version: 2"):
            enrich_helpers(frames, {})


# ---------------------------------------------------------------------------
# Acceptance: provenance-driven cleanup (no prefix fallback)
# ---------------------------------------------------------------------------

class TestProvenanceDrivenCleanup:

    def test_cleanup_uses_provenance_not_prefix(self):
        inferred = infer_fk_relations(_orders_and_products())
        enriched = enrich_helpers(inferred, {})
        # Inject a non-helper underscore-prefixed column the prefix-only
        # fallback would have removed; provenance-driven cleanup keeps it.
        enriched["orders"][("_user_note",) + ("",) * 2] = ["x", "y"]

        cleaned = drop_helpers(enriched)
        cols = [c[0] if isinstance(c, tuple) else c for c in cleaned["orders"].columns]
        assert "_products_name" not in cols
        assert "_user_note" in cols

    def test_reimport_cleanup_via_provenance_only(self):
        """After a workbook reimport the user might rerun the cleanup step
        on frames that still carry helper columns alongside provenance;
        cleanup follows provenance exactly.
        """
        inferred = infer_fk_relations(_orders_and_products())
        enriched = enrich_helpers(inferred, {})

        # Simulate reimport-time state: helper columns are present plus
        # provenance entries. No prefix fallback needed.
        cleaned = drop_helpers(enriched)
        cols = [c[0] if isinstance(c, tuple) else c for c in cleaned["orders"].columns]
        assert "_products_name" not in cols
        assert "code_(products)" in cols


# ---------------------------------------------------------------------------
# Acceptance: validation through target_key
# ---------------------------------------------------------------------------

class TestValidationUsesTargetKey:

    def test_value_mismatch_resolved_via_target_key_in_policy(self):
        frames = _orders_and_products()
        frames["orders"]["_products_name"] = ["WRONG", "Beta"]
        configured = configure_fk_helpers(
            frames,
            target="products",
            key="code",
            allowed_helpers=["name"],
            default_helpers=["name"],
        )

        findings = check_helper_values(configured, {})
        mismatches = [f for f in findings if f.column == "_products_name"]
        assert mismatches, findings

    def test_missing_helper_flagged_against_declared_relation(self):
        frames = _orders_and_products()
        configured = configure_fk_helpers(
            frames,
            target="products",
            key="code",
            allowed_helpers=["name"],
            default_helpers=["name"],
        )

        findings = check_missing_helpers(configured, {})
        missing = [f for f in findings if f.column == "_products_name"]
        assert missing, findings

    def test_unresolvable_fk_uses_target_key_from_policy(self):
        frames = _orders_and_products()
        frames["orders"].loc[0, "code_(products)"] = "missing"
        configured = configure_fk_helpers(
            frames,
            target="products",
            key="code",
            allowed_helpers=["name"],
            default_helpers=["name"],
        )

        findings = check_unresolvable_fks(configured, {})
        unresolvable = [f for f in findings if f.column == "code_(products)"]
        assert unresolvable, findings


# ---------------------------------------------------------------------------
# Reorder primitive uses policy / provenance, not FK_PATTERN
# ---------------------------------------------------------------------------

class TestReorderUsesPolicyOrProvenance:

    def test_reorder_via_provenance_after_enrichment(self):
        inferred = infer_fk_relations(
            _orders_and_products(),
            id_columns=["code"],
            fk_patterns=["code_({target})"],
        )
        enriched = enrich_helpers(inferred, {})

        # Move the materialized helper column to position 0 so reorder has
        # work to do; drop the original tail occurrence.
        helper_label = "_products_name"
        helper_column = next(
            column for column in enriched["orders"].columns
            if (column[0] if isinstance(column, tuple) else column) == helper_label
        )
        helper_values = enriched["orders"][helper_column].tolist()
        without_helper = [
            column for column in enriched["orders"].columns
            if (column[0] if isinstance(column, tuple) else column) != helper_label
        ]
        relocated = enriched["orders"].loc[:, without_helper].copy()
        relocated.insert(0, helper_column, helper_values)
        enriched["orders"] = relocated

        step = reorder_helpers_next_to_fk()
        out = step(enriched)

        lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["orders"].columns]
        assert lvl0.index("_products_name") == lvl0.index("code_(products)") + 1

    def test_reorder_via_v2_policy_when_provenance_absent(self):
        """A frame may arrive with helper columns but no provenance (e.g.
        after a reimport). The v2 policy declares the helper-to-FK pairing
        so reorder can still place the helper correctly.
        """
        frames = _orders_and_products()
        frames["orders"]["_products_name"] = ["Alpha", "Beta"]
        # Force helper to the left of FK column.
        frames["orders"] = frames["orders"][["order_id", "_products_name", "code_(products)"]]
        configured = configure_fk_helpers(
            frames,
            target="products",
            key="code",
            allowed_helpers=["name"],
            default_helpers=["name"],
        )

        step = reorder_helpers_next_to_fk()
        out = step(configured)

        lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["orders"].columns]
        assert lvl0 == ["order_id", "code_(products)", "_products_name"]
