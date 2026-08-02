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


@pytest.mark.ftr("BUG-HELPER-CLEANUP-CONTRACT-P4A")
def test_drop_uses_durable_workbook_helper_columns_when_derived_is_absent() -> None:
    frames = {
        "_meta": {"sheets": {"orders": {"helper_columns": ["_customer_name"]}}},
        "orders": pd.DataFrame(
            [
                {
                    "order_id": "o1",
                    "customer_id": "c1",
                    "_customer_name": "Alice",
                    "amount": 100,
                }
            ]
        ),
    }

    out = apply_derived_column_policy(frames, source="orders", policy="drop")

    assert list(out["orders"].columns) == ["order_id", "customer_id", "amount"]
    assert "_customer_name" in frames["orders"].columns
    assert out["_meta"]["sheets"]["orders"]["helper_columns"] == ["_customer_name"]


@pytest.mark.ftr("BUG-HELPER-CLEANUP-CONTRACT-P4A")
def test_no_derived_or_durable_helper_carrier_is_conservative_noop() -> None:
    frames = {
        "orders": pd.DataFrame(
            [{"order_id": "o1", "customer_id": "c1", "_customer_name": "Alice"}]
        )
    }

    out = apply_derived_column_policy(frames, source="orders", policy="drop")

    assert list(out["orders"].columns) == ["order_id", "customer_id", "_customer_name"]


@pytest.mark.ftr("BUG-HELPER-CLEANUP-CONTRACT-P4A")
def test_durable_helper_cleanup_preserves_non_helper_columns() -> None:
    frames = {
        "_meta": {"sheets": {"orders": {"helper_columns": ["_customer_name"]}}},
        "orders": pd.DataFrame(
            [
                {
                    "order_id": "o1",
                    "customer_id": "c1",
                    "_customer_name": "Alice",
                    "_manual_note": "keep",
                }
            ]
        ),
    }

    out = apply_derived_column_policy(frames, source="orders", policy="drop")

    assert list(out["orders"].columns) == ["order_id", "customer_id", "_manual_note"]


@pytest.mark.ftr("BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A")
def test_policy_fallback_drops_declared_fk_helpers_after_persistence_boundary() -> None:
    frames = {
        "_meta": {
            "helper_policies": {
                "fk": {
                    "schema_version": 2,
                    "relations": [
                        {
                            "source_frame": "groups",
                            "source_column": "home_place_id",
                            "target_frame": "places",
                            "target_key": "id",
                            "helper_columns": [
                                {
                                    "column": "_places_name",
                                    "target_field": "name",
                                }
                            ],
                        }
                    ],
                }
            }
        },
        "groups": pd.DataFrame(
            [
                {
                    "id": "GROUP-0001",
                    "home_place_id": "PLACE-0007",
                    "_places_name": "Microraptorenwald",
                    "_manual_note": "keep",
                }
            ]
        ),
    }

    out = apply_derived_column_policy(frames, source="groups", policy="drop")

    assert list(out["groups"].columns) == ["id", "home_place_id", "_manual_note"]
    assert "_places_name" in frames["groups"].columns


@pytest.mark.ftr("BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A")
def test_durable_fk_policy_fallback_drops_declared_helpers() -> None:
    # FK Helper Slice 2 (v1 retirement): the durable v2 relation model is the
    # policy fallback for cleanup. With no runtime provenance and no
    # `sheets.<frame>.helper_columns`, the v2 relation's `helper_columns`
    # identify which columns to drop.
    frames = {
        "_meta": {
            "helper_policies": {
                "fk": {
                    "schema_version": 2,
                    "relations": [
                        {
                            "source_frame": "groups",
                            "source_column": "home_place_id",
                            "target_frame": "places",
                            "target_key": "id",
                            "helper_columns": [
                                {"column": "_places_name", "target_field": "name"}
                            ],
                            "produced_by": {"step": "configure_fk_helpers", "mode": "explicit"},
                        }
                    ],
                }
            }
        },
        "groups": pd.DataFrame(
            [
                {
                    "id": "GROUP-0001",
                    "home_place_id": "PLACE-0007",
                    "_places_name": "Microraptorenwald",
                    "_manual_note": "keep",
                }
            ]
        ),
    }

    out = apply_derived_column_policy(frames, source="groups", policy="drop")

    assert list(out["groups"].columns) == ["id", "home_place_id", "_manual_note"]


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


# ---------------------------------------------------------------------------
# Review 001 IMP-002: asymmetric enrich_lookup mismatch checking
# (FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2 Slice 1)
# ---------------------------------------------------------------------------

_asym = pytest.mark.ftr("FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2")


def _frames_with_asymmetric_lookup_helper(*, edited: bool = False, unmatched: bool = False):
    """matrix frame keyed by ``story_id`` with a helper materialized from
    ``stories`` keyed by the differently named ``id``.
    """
    stories = pd.DataFrame([
        {"id": "s1", "title": "First"},
        {"id": "s2", "title": "Second"},
    ])
    rows = [
        {"story_id": "s1", "title": "First" if not edited else "EDITED", "dyn": "a"},
        {"story_id": "s2", "title": "Second", "dyn": "b"},
    ]
    if unmatched:
        rows.append({"story_id": "s999", "title": "Orphan", "dyn": "c"})
    matrix = pd.DataFrame(rows)
    meta = {
        "derived": {
            "sheets": {
                "matrix": {
                    "enrich_lookup": {
                        "lookup": "stories",
                        "source_key": "story_id",
                        "lookup_key": "id",
                        "helper_columns": ["title"],
                    }
                }
            }
        }
    }
    return {"_meta": meta, "stories": stories, "matrix": matrix}


@_asym
def test_asymmetric_unchanged_helper_warn_mode_emits_no_findings() -> None:
    frames = _frames_with_asymmetric_lookup_helper()

    out = apply_derived_column_policy(frames, source="matrix", policy="warn_on_mismatch")

    findings = out["derived_column_findings"]
    assert list(findings.columns) == FINDING_COLUMNS
    assert len(findings) == 0
    assert "title" not in out["matrix"].columns


@_asym
def test_asymmetric_edited_helper_warn_mode_emits_finding_without_raising() -> None:
    frames = _frames_with_asymmetric_lookup_helper(edited=True)

    out = apply_derived_column_policy(frames, source="matrix", policy="warn_on_mismatch")

    findings = out["derived_column_findings"]
    assert len(findings) == 1
    row = findings.iloc[0]
    assert row["rule_type"] == "derived_value_mismatch"
    assert row["columns"] == "title"
    assert row["severity"] == "warn"
    assert "title" not in out["matrix"].columns


@_asym
def test_asymmetric_unchanged_helper_fail_mode_does_not_raise() -> None:
    frames = _frames_with_asymmetric_lookup_helper()

    out = apply_derived_column_policy(frames, source="matrix", policy="fail_on_mismatch")

    assert "title" not in out["matrix"].columns


@_asym
def test_asymmetric_edited_helper_fail_mode_raises() -> None:
    frames = _frames_with_asymmetric_lookup_helper(edited=True)

    with pytest.raises(ValueError, match="derived_value_mismatch"):
        apply_derived_column_policy(frames, source="matrix", policy="fail_on_mismatch")


@_asym
def test_asymmetric_unmatched_source_reference_is_not_a_mismatch() -> None:
    # An unmatched source key (no lookup row) is a separate concern and must not
    # be reported as a value mismatch — consistent with symmetric behaviour.
    frames = _frames_with_asymmetric_lookup_helper(unmatched=True)

    out = apply_derived_column_policy(frames, source="matrix", policy="warn_on_mismatch")

    assert len(out["derived_column_findings"]) == 0
    assert "title" not in out["matrix"].columns


@_asym
def test_asymmetric_malformed_partial_provenance_raises_clear_error() -> None:
    frames = _frames_with_asymmetric_lookup_helper()
    # Drop the lookup_key half: partial asymmetric provenance must be rejected,
    # not silently skipped.
    del frames["_meta"]["derived"]["sheets"]["matrix"]["enrich_lookup"]["lookup_key"]

    with pytest.raises(ValueError, match=r"requires both `source_key` and `lookup_key`"):
        apply_derived_column_policy(frames, source="matrix", policy="warn_on_mismatch")


@_asym
def test_asymmetric_mixed_on_and_asymmetric_provenance_raises() -> None:
    frames = _frames_with_asymmetric_lookup_helper()
    frames["_meta"]["derived"]["sheets"]["matrix"]["enrich_lookup"]["on"] = ["story_id"]

    with pytest.raises(ValueError, match="mixes symmetric `on` with asymmetric"):
        apply_derived_column_policy(frames, source="matrix", policy="warn_on_mismatch")


@_asym
def test_asymmetric_drop_mode_is_value_blind() -> None:
    # policy: drop must never value-check, even with an edited asymmetric helper.
    frames = _frames_with_asymmetric_lookup_helper(edited=True)

    out = apply_derived_column_policy(frames, source="matrix", policy="drop")

    assert "title" not in out["matrix"].columns
    assert "derived_column_findings" not in out


# ---------------------------------------------------------------------------
# Review 002 R002-IMP-002: mismatch verification must fail closed
# ---------------------------------------------------------------------------


def _enrich_spec(frames):
    return frames["_meta"]["derived"]["sheets"]["matrix"]["enrich_lookup"]


@_asym
@pytest.mark.parametrize("policy", ["warn_on_mismatch", "fail_on_mismatch"])
@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda s: s.__setitem__("source_key", "   "), r"source_key must be a single non-empty string"),
        (lambda s: s.__setitem__("lookup_key", ""), r"lookup_key must be a single non-empty string"),
        (lambda s: s.__setitem__("source_key", ["story_id"]), r"source_key must be a single non-empty string.*list"),
        (lambda s: s.__setitem__("lookup_key", 123), r"lookup_key must be a single non-empty string.*int"),
    ],
)
def test_asymmetric_malformed_key_metadata_raises(policy, mutate, match) -> None:
    frames = _frames_with_asymmetric_lookup_helper(edited=True)
    mutate(_enrich_spec(frames))
    with pytest.raises(ValueError, match=match):
        apply_derived_column_policy(frames, source="matrix", policy=policy)


@_asym
def test_asymmetric_missing_payload_key_column_fail_raises() -> None:
    frames = _frames_with_asymmetric_lookup_helper(edited=True)
    # Drop the source key column from the payload -> cannot verify.
    frames["matrix"] = frames["matrix"].drop(columns=["story_id"])
    with pytest.raises(ValueError, match="Derived column policy failed"):
        apply_derived_column_policy(frames, source="matrix", policy="fail_on_mismatch")


@_asym
def test_asymmetric_missing_payload_key_column_warn_emits_unverifiable_finding() -> None:
    frames = _frames_with_asymmetric_lookup_helper(edited=True)
    frames["matrix"] = frames["matrix"].drop(columns=["story_id"])
    out = apply_derived_column_policy(frames, source="matrix", policy="warn_on_mismatch")
    findings = out["derived_column_findings"]
    assert len(findings) == 1
    row = findings.iloc[0]
    assert row["rule_type"] == "unverifiable_enrich_lookup"
    assert "story_id" in row["message"]


@_asym
def test_asymmetric_missing_lookup_key_column_fail_raises() -> None:
    frames = _frames_with_asymmetric_lookup_helper(edited=True)
    frames["stories"] = frames["stories"].drop(columns=["id"])
    with pytest.raises(ValueError, match="Derived column policy failed"):
        apply_derived_column_policy(frames, source="matrix", policy="fail_on_mismatch")


@_asym
def test_asymmetric_missing_lookup_key_column_warn_emits_unverifiable_finding() -> None:
    frames = _frames_with_asymmetric_lookup_helper(edited=True)
    frames["stories"] = frames["stories"].drop(columns=["id"])
    out = apply_derived_column_policy(frames, source="matrix", policy="warn_on_mismatch")
    findings = out["derived_column_findings"]
    assert len(findings) == 1
    assert findings.iloc[0]["rule_type"] == "unverifiable_enrich_lookup"
    assert "id" in findings.iloc[0]["message"]


# --- Symmetric `on` shape validation ---------------------------------------


def _symmetric_enrich_spec(frames):
    return frames["_meta"]["derived"]["sheets"]["orders"]["enrich_lookup"]


@pytest.mark.parametrize("policy", ["warn_on_mismatch", "fail_on_mismatch"])
@pytest.mark.parametrize(
    "on_value, match",
    [
        ("customer_id", r"on must be a non-empty list.*str"),
        (123, r"on must be a non-empty list.*int"),
        ({"customer_id": 1}, r"on must be a non-empty list.*dict"),
        ([], r"on must be a non-empty list.*empty list"),
        ([""], r"on\[0\] must be a non-empty string.*blank"),
        ([123], r"on\[0\] must be a non-empty string.*int"),
    ],
)
def test_symmetric_malformed_on_raises(policy, on_value, match) -> None:
    frames = _frames_with_fk_and_lookup_helpers(edited_lookup=True)
    _symmetric_enrich_spec(frames)["on"] = on_value
    with pytest.raises(ValueError, match=match):
        apply_derived_column_policy(frames, source="orders", policy=policy)


def test_symmetric_valid_on_still_passes_and_detects_edit() -> None:
    # Regression: a valid symmetric on list still value-checks correctly.
    frames = _frames_with_fk_and_lookup_helpers(edited_lookup=True)
    with pytest.raises(ValueError, match="derived_value_mismatch"):
        apply_derived_column_policy(frames, source="orders", policy="fail_on_mismatch")


# --- Valid records remain verifiable (regression guards) --------------------


@_asym
def test_asymmetric_null_key_valid_and_edit_detected() -> None:
    stories = pd.DataFrame([
        {"id": None, "title": "NullKey"},
        {"id": "s2", "title": "Second"},
    ])
    matrix = pd.DataFrame([
        {"story_id": None, "title": "EDITED", "dyn": "a"},
        {"story_id": "s2", "title": "Second", "dyn": "b"},
    ])
    meta = {
        "derived": {"sheets": {"matrix": {"enrich_lookup": {
            "lookup": "stories", "source_key": "story_id", "lookup_key": "id",
            "helper_columns": ["title"],
        }}}}
    }
    frames = {"_meta": meta, "stories": stories, "matrix": matrix}
    out = apply_derived_column_policy(frames, source="matrix", policy="warn_on_mismatch")
    findings = out["derived_column_findings"]
    # The null-keyed edited row is detected against the null-keyed canonical row.
    assert len(findings) == 1
    assert findings.iloc[0]["rule_type"] == "derived_value_mismatch"


@_asym
def test_asymmetric_duplicate_lookup_keys_first_occurrence_wins() -> None:
    stories = pd.DataFrame([
        {"id": "s1", "title": "First"},
        {"id": "s1", "title": "Dup"},
        {"id": "s2", "title": "Second"},
    ])
    matrix = pd.DataFrame([
        {"story_id": "s1", "title": "First", "dyn": "a"},
        {"story_id": "s2", "title": "Second", "dyn": "b"},
    ])
    meta = {
        "derived": {"sheets": {"matrix": {"enrich_lookup": {
            "lookup": "stories", "source_key": "story_id", "lookup_key": "id",
            "helper_columns": ["title"],
        }}}}
    }
    frames = {"_meta": meta, "stories": stories, "matrix": matrix}
    out = apply_derived_column_policy(frames, source="matrix", policy="warn_on_mismatch")
    # First occurrence (First) wins deterministically -> unchanged row passes.
    assert len(out["derived_column_findings"]) == 0


# ---------------------------------------------------------------------------
# Review 003 R003-IMP-001: absent / explicitly null key forms must fail closed
# ---------------------------------------------------------------------------


def _frames_with_key_form(key_form: dict):
    """Edited-helper payload whose proper provenance would fail under
    ``fail_on_mismatch``; ``key_form`` supplies the (possibly malformed)
    join-key members of the enrich_lookup record.
    """
    stories = pd.DataFrame([
        {"id": "s1", "title": "First"},
        {"id": "s2", "title": "Second"},
    ])
    matrix = pd.DataFrame([
        {"story_id": "s1", "title": "EDITED", "dyn": "a"},
        {"story_id": "s2", "title": "Second", "dyn": "b"},
    ])
    spec = {"lookup": "stories", "helper_columns": ["title"]}
    spec.update(key_form)
    meta = {"derived": {"sheets": {"matrix": {"enrich_lookup": spec}}}}
    return {"_meta": meta, "stories": stories, "matrix": matrix}


# Each malformed key form together with the ValueError message fragment it must
# raise. These are the exact shapes reproduced by Review 003.
_MALFORMED_KEY_FORMS = [
    pytest.param({}, "has no join-key form", id="no_key_form"),
    pytest.param({"on": None}, r"on must be a non-empty list", id="on_null"),
    pytest.param({"source_key": None}, r"requires both `source_key` and `lookup_key`", id="source_key_null_only"),
    pytest.param({"lookup_key": None}, r"requires both `source_key` and `lookup_key`", id="lookup_key_null_only"),
    pytest.param({"source_key": None, "lookup_key": None}, r"source_key must be a single non-empty string", id="both_null"),
    pytest.param({"source_key": "story_id", "lookup_key": None}, r"lookup_key must be a single non-empty string", id="valid_source_null_lookup"),
    pytest.param({"source_key": None, "lookup_key": "id"}, r"source_key must be a single non-empty string", id="null_source_valid_lookup"),
    pytest.param({"on": None, "source_key": "story_id"}, r"mixes symmetric `on` with asymmetric", id="mixed_on_null_plus_asym"),
    pytest.param({"on": ["story_id"], "lookup_key": None}, r"mixes symmetric `on` with asymmetric", id="mixed_valid_on_plus_null_asym"),
]


@_asym
@pytest.mark.parametrize("policy", ["warn_on_mismatch", "fail_on_mismatch"])
@pytest.mark.parametrize("key_form, match", _MALFORMED_KEY_FORMS)
def test_malformed_or_absent_key_form_fails_closed(policy, key_form, match) -> None:
    frames = _frames_with_key_form(key_form)
    with pytest.raises(ValueError, match=match):
        apply_derived_column_policy(frames, source="matrix", policy=policy)
    # The path is always named in the diagnostic.
    with pytest.raises(ValueError, match=r"_meta\.derived\.sheets\['matrix'\]\.enrich_lookup"):
        apply_derived_column_policy(frames, source="matrix", policy=policy)


@_asym
@pytest.mark.parametrize("policy", ["warn_on_mismatch", "fail_on_mismatch"])
def test_malformed_key_form_leaves_caller_state_and_provenance_unchanged(policy) -> None:
    frames = _frames_with_key_form({"source_key": None})
    matrix_before = frames["matrix"].copy(deep=True)
    stories_before = frames["stories"].copy(deep=True)
    prov_before = dict(frames["_meta"]["derived"]["sheets"]["matrix"]["enrich_lookup"])

    with pytest.raises(ValueError):
        apply_derived_column_policy(frames, source="matrix", policy=policy)

    pd.testing.assert_frame_equal(frames["matrix"], matrix_before)
    pd.testing.assert_frame_equal(frames["stories"], stories_before)
    # Helper column and provenance are not consumed on failure.
    assert "title" in frames["matrix"].columns
    assert frames["_meta"]["derived"]["sheets"]["matrix"]["enrich_lookup"] == prov_before


@_asym
@pytest.mark.parametrize(
    "key_form",
    [{}, {"on": None}, {"source_key": None}, {"source_key": None, "lookup_key": None}],
)
def test_malformed_key_form_drop_is_value_blind(key_form) -> None:
    # policy: drop must never invoke key-form validation; it drops by identity.
    frames = _frames_with_key_form(key_form)
    out = apply_derived_column_policy(frames, source="matrix", policy="drop")
    assert "title" not in out["matrix"].columns
    assert "derived_column_findings" not in out


@_asym
@pytest.mark.parametrize("policy", ["warn_on_mismatch", "fail_on_mismatch"])
def test_valid_asymmetric_record_still_detects_edit(policy) -> None:
    frames = _frames_with_key_form({"source_key": "story_id", "lookup_key": "id"})
    if policy == "fail_on_mismatch":
        with pytest.raises(ValueError, match="derived_value_mismatch"):
            apply_derived_column_policy(frames, source="matrix", policy=policy)
    else:
        out = apply_derived_column_policy(frames, source="matrix", policy=policy)
        assert len(out["derived_column_findings"]) == 1


@pytest.mark.ftr("FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2")
@pytest.mark.parametrize("policy", ["warn_on_mismatch", "fail_on_mismatch"])
def test_valid_symmetric_record_still_detects_edit(policy) -> None:
    frames = _frames_with_fk_and_lookup_helpers(edited_lookup=True)  # symmetric on: [customer_id]
    if policy == "fail_on_mismatch":
        with pytest.raises(ValueError, match="derived_value_mismatch"):
            apply_derived_column_policy(frames, source="orders", policy=policy)
    else:
        out = apply_derived_column_policy(frames, source="orders", policy=policy)
        assert len(out["derived_column_findings"]) == 1


@_asym
@pytest.mark.parametrize("policy", ["warn_on_mismatch", "fail_on_mismatch"])
def test_absent_enrich_lookup_record_is_still_a_safe_noop(policy) -> None:
    # Absence of the entire enrich_lookup record (not merely its key form) is the
    # established safe no-op, distinct from a present record with no key form.
    orders = pd.DataFrame([{"order_id": "o1", "amount": 100}])
    frames = {"orders": orders}
    out = apply_derived_column_policy(frames, source="orders", policy=policy)
    assert list(out["orders"].columns) == ["order_id", "amount"]
    if policy == "warn_on_mismatch":
        assert len(out["derived_column_findings"]) == 0
