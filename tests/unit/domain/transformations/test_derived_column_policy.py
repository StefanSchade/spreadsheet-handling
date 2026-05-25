"""Tests for the reimport derived-column policy step.

FTR-WORKBOOK-REIMPORT-DERIVED-COLUMN-POLICY-P4A — slice 1.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.derived_column_policy import (
    FINDING_COLUMNS,
    apply_derived_column_policy,
    enforce_derived_column_policy_frame,
)
from spreadsheet_handling.domain.transformations.fk_helpers import drop_helpers
from spreadsheet_handling.pipeline import REGISTRY, build_steps_from_config, run_pipeline
from spreadsheet_handling.pipeline.types import StepRegistration

pytestmark = pytest.mark.ftr("FTR-WORKBOOK-REIMPORT-DERIVED-COLUMN-POLICY-P4A")


def _frames_with_fk_and_lookup_helpers(*, edited_lookup: bool = False, edited_fk: bool = False):
    """orders frame with one FK helper column and one enrich_lookup helper column."""
    customers = pd.DataFrame([
        {"customer_id": "c1", "name": "Alice", "tier": "gold"},
        {"customer_id": "c2", "name": "Bob", "tier": "silver"},
    ])
    orders = pd.DataFrame([
        {
            "order_id": "o1",
            "customer_id": "c1",
            "_customer_name": "Alice" if not edited_fk else "EDITED",
            "tier": "gold" if not edited_lookup else "EDITED",
            "amount": 100,
        },
        {
            "order_id": "o2",
            "customer_id": "c2",
            "_customer_name": "Bob",
            "tier": "silver",
            "amount": 200,
        },
    ])
    meta = {
        "derived": {
            "sheets": {
                "orders": {
                    "helper_columns": [
                        {
                            "column": "_customer_name",
                            "fk_column": "customer_id",
                            "target": "customers",
                            "value_field": "name",
                        }
                    ],
                    "enrich_lookup": {
                        "lookup": "customers",
                        "on": ["customer_id"],
                        "helper_columns": ["tier"],
                    },
                }
            }
        }
    }
    return {"_meta": meta, "customers": customers, "orders": orders}


def test_drop_removes_fk_and_lookup_helper_columns() -> None:
    frames = _frames_with_fk_and_lookup_helpers()

    out = apply_derived_column_policy(frames, source="orders", policy="drop")

    cols = list(out["orders"].columns)
    assert "_customer_name" not in cols  # FK helper dropped
    assert "tier" not in cols            # enrich_lookup helper dropped
    assert cols == ["order_id", "customer_id", "amount"]
    assert "derived_column_findings" not in out


def test_unchanged_lookup_helper_warn_mode_emits_no_findings() -> None:
    frames = _frames_with_fk_and_lookup_helpers()

    out = apply_derived_column_policy(frames, source="orders", policy="warn_on_mismatch")

    findings = out["derived_column_findings"]
    assert list(findings.columns) == FINDING_COLUMNS
    assert len(findings) == 0
    assert "tier" not in out["orders"].columns


def test_edited_lookup_helper_warn_mode_emits_finding_without_raising() -> None:
    frames = _frames_with_fk_and_lookup_helpers(edited_lookup=True)

    out = apply_derived_column_policy(frames, source="orders", policy="warn_on_mismatch")

    findings = out["derived_column_findings"]
    assert len(findings) == 1
    row = findings.iloc[0]
    assert row["rule_type"] == "derived_value_mismatch"
    assert row["columns"] == "tier"
    assert row["severity"] == "warn"
    assert "tier" not in out["orders"].columns


def test_edited_lookup_helper_fail_mode_raises() -> None:
    frames = _frames_with_fk_and_lookup_helpers(edited_lookup=True)

    with pytest.raises(ValueError, match="derived_value_mismatch"):
        apply_derived_column_policy(frames, source="orders", policy="fail_on_mismatch")


def test_edited_fk_helper_is_dropped_but_not_value_checked_in_slice1() -> None:
    # FK helper value edited; slice 1 must drop it but emit NO mismatch finding.
    frames = _frames_with_fk_and_lookup_helpers(edited_fk=True)

    out = apply_derived_column_policy(frames, source="orders", policy="warn_on_mismatch")

    assert "_customer_name" not in out["orders"].columns
    findings = out["derived_column_findings"]
    assert len(findings) == 0  # FK value-check deferred to a later slice


def test_identity_comes_only_from_provenance_no_name_heuristic() -> None:
    # An underscore-prefixed column NOT in provenance must survive.
    frames = _frames_with_fk_and_lookup_helpers()
    frames["orders"]["_not_registered"] = ["x", "y"]

    out = apply_derived_column_policy(frames, source="orders", policy="drop")

    assert "_not_registered" in out["orders"].columns
    assert "_customer_name" not in out["orders"].columns


def test_no_derived_meta_is_documented_noop() -> None:
    # Running after drop_helpers cleanup (no _meta.derived) drops nothing.
    orders = pd.DataFrame([{"order_id": "o1", "amount": 100}])
    frames = {"orders": orders}

    out = apply_derived_column_policy(frames, source="orders", policy="warn_on_mismatch")

    assert list(out["orders"].columns) == ["order_id", "amount"]
    assert list(out["derived_column_findings"].columns) == FINDING_COLUMNS
    assert len(out["derived_column_findings"]) == 0


def test_mixed_editable_helper_sheet_preserves_payload_columns() -> None:
    frames = _frames_with_fk_and_lookup_helpers()

    out = apply_derived_column_policy(frames, source="orders", output="orders_payload", policy="drop")

    payload = out["orders_payload"]
    assert set(payload.columns) == {"order_id", "customer_id", "amount"}
    # original source frame untouched when output differs
    assert "_customer_name" in out["orders"].columns


def test_pure_function_returns_payload_and_findings() -> None:
    frames = _frames_with_fk_and_lookup_helpers(edited_lookup=True)
    sheet_meta = frames["_meta"]["derived"]["sheets"]["orders"]

    cleaned, findings = enforce_derived_column_policy_frame(
        frames["orders"],
        frame_name="orders",
        derived_meta=sheet_meta,
        lookup_frames={"customers": frames["customers"]},
        policy="warn_on_mismatch",
    )

    assert "tier" not in cleaned.columns
    assert "_customer_name" not in cleaned.columns
    assert len(findings) == 1
    assert findings[0].rule_type == "derived_value_mismatch"


def test_invalid_policy_raises() -> None:
    frames = _frames_with_fk_and_lookup_helpers()

    with pytest.raises(ValueError, match="Unsupported policy"):
        apply_derived_column_policy(frames, source="orders", policy="bogus")


def test_step_is_config_addressable() -> None:
    frames = _frames_with_fk_and_lookup_helpers()

    steps = build_steps_from_config([{
        "step": "apply_derived_column_policy",
        "source": "orders",
        "policy": "drop",
    }])

    assert isinstance(REGISTRY["apply_derived_column_policy"], StepRegistration)
    assert steps[0].config["target"].endswith(":apply_derived_column_policy")

    out = run_pipeline(frames, steps)
    assert "_customer_name" not in out["orders"].columns
    assert "tier" not in out["orders"].columns


# --- Review blocker fixes: provenance lifecycle + malformed-shape hardening ---


def test_default_replacement_removes_consumed_fk_and_enrich_provenance() -> None:
    frames = _frames_with_fk_and_lookup_helpers()

    out = apply_derived_column_policy(frames, source="orders", policy="drop")

    sheets = out["_meta"].get("derived", {}).get("sheets", {})
    # consumed provenance for the replaced source frame is gone, container pruned
    assert "orders" not in sheets
    # original input meta is not mutated
    assert "orders" in frames["_meta"]["derived"]["sheets"]


def test_followed_by_remove_fk_helpers_leaves_no_stale_enrich_provenance() -> None:
    """``apply_derived_column_policy`` followed by ``remove_fk_helpers`` is a
    no-op when the policy step already consumed the provenance. After
    FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5 the second step requires
    policy or provenance; if both are absent it raises clearly, so the
    pipeline does not silently bypass the cleanup contract.
    """
    frames = _frames_with_fk_and_lookup_helpers()

    out = run_pipeline(
        frames,
        build_steps_from_config([
            {"step": "apply_derived_column_policy", "source": "orders", "policy": "drop"},
        ]),
    )

    derived = out["_meta"].get("derived", {})
    sheets = derived.get("sheets", {})
    assert "orders" not in sheets
    assert "_customer_name" not in out["orders"].columns
    assert "tier" not in out["orders"].columns

    with pytest.raises(ValueError, match="infer_fk_relations"):
        run_pipeline(out, build_steps_from_config([{"step": "remove_fk_helpers"}]))


def test_distinct_output_preserves_original_source_provenance() -> None:
    frames = _frames_with_fk_and_lookup_helpers()

    out = apply_derived_column_policy(
        frames, source="orders", output="orders_payload", policy="drop"
    )

    src_meta = out["_meta"]["derived"]["sheets"]["orders"]
    assert "_customer_name" in {e["column"] for e in src_meta["helper_columns"]}
    assert src_meta["enrich_lookup"]["helper_columns"] == ["tier"]
    assert "_customer_name" in out["orders"].columns          # source untouched
    assert "_customer_name" not in out["orders_payload"].columns


def test_drop_helpers_prunes_enrich_provenance_only_when_columns_absent() -> None:
    # enrich columns already removed -> drop_helpers prunes the stale subkey
    frames = _frames_with_fk_and_lookup_helpers()
    frames["orders"] = frames["orders"].drop(columns=["tier", "_customer_name"])

    out = drop_helpers(frames)

    assert "orders" not in out["_meta"].get("derived", {}).get("sheets", {})


def test_drop_helpers_keeps_enrich_provenance_when_columns_still_present() -> None:
    # enrich column still present -> drop_helpers must NOT orphan it
    frames = _frames_with_fk_and_lookup_helpers()
    # remove only the FK helper so helper_columns is cleaned but enrich stays
    frames["orders"] = frames["orders"].drop(columns=["_customer_name"])

    out = drop_helpers(frames)

    enrich = out["_meta"]["derived"]["sheets"]["orders"]["enrich_lookup"]
    assert enrich["helper_columns"] == ["tier"]
    assert "helper_columns" not in out["_meta"]["derived"]["sheets"]["orders"]


def test_malformed_sheet_level_provenance_raises_clear_value_error() -> None:
    frames = _frames_with_fk_and_lookup_helpers()
    frames["_meta"]["derived"]["sheets"]["orders"] = "bad"

    with pytest.raises(ValueError, match=r"_meta\.derived\.sheets\['orders'\] must be a mapping"):
        apply_derived_column_policy(frames, source="orders", policy="drop")


def test_malformed_helper_columns_entry_raises_clear_value_error() -> None:
    frames = _frames_with_fk_and_lookup_helpers()
    frames["_meta"]["derived"]["sheets"]["orders"]["helper_columns"] = ["_h"]

    with pytest.raises(ValueError, match=r"helper_columns\[0\] must be a mapping"):
        apply_derived_column_policy(frames, source="orders", policy="drop")


def test_malformed_derived_container_raises_clear_value_error() -> None:
    orders = pd.DataFrame([{"order_id": "o1", "amount": 1}])
    frames = {"_meta": {"derived": "bad"}, "orders": orders}

    with pytest.raises(ValueError, match=r"_meta\.derived must be a mapping"):
        apply_derived_column_policy(frames, source="orders", policy="drop")


def test_stale_provenance_referencing_absent_helper_columns_is_safe() -> None:
    # provenance advertises a column the frame no longer has -> safe no-op,
    # and the stale entry is still pruned on replacement.
    frames = _frames_with_fk_and_lookup_helpers()
    frames["orders"] = frames["orders"].drop(columns=["_customer_name"])

    out = apply_derived_column_policy(frames, source="orders", policy="warn_on_mismatch")

    assert "tier" not in out["orders"].columns
    assert len(out["derived_column_findings"]) == 0
    assert "orders" not in out["_meta"].get("derived", {}).get("sheets", {})
