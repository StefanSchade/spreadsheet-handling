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
from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup
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
def test_durable_fk_policy_alone_does_not_authorize_deletion_after_persistence_boundary() -> None:
    """Slice 5 (deletion-authority design): inverted from the pre-Slice-5
    behavior. Durable v2 FK relation policy alone -- no truthful transient
    provenance for the sheet -- never authorizes deletion, regardless of
    whether the durable declaration was written before or after a simulated
    persistence boundary. The column must survive; see accepted design
    ``derived_artifact_deletion_authority_design_2026-08-21.adoc`` Section
    F/H and Section I's disposition of this test.
    """
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

    assert list(out["groups"].columns) == [
        "id", "home_place_id", "_places_name", "_manual_note",
    ]
    assert "_places_name" in frames["groups"].columns


@pytest.mark.ftr("BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A")
def test_durable_fk_policy_alone_does_not_authorize_deletion() -> None:
    """Slice 5: inverted from the pre-Slice-5 behavior.

    With no runtime provenance and no `sheets.<frame>.helper_columns`, the
    v2 relation's `helper_columns` identify what FK *would* request, not
    what FK currently produced, so they no longer authorize deletion; the
    column survives.
    """
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

    assert list(out["groups"].columns) == [
        "id", "home_place_id", "_places_name", "_manual_note",
    ]


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


# ---------------------------------------------------------------------------
# Slice 5 (FK Helper Deletion Authority design,
# derived_artifact_deletion_authority_design_2026-08-21.adoc): durable FK
# relation policy is removed as DCP deletion authority (Section F/H), and DCP
# enforces the write-time publication-lifecycle rule over its own complete
# publication inventory -- the primary payload write (effective target
# `payload_target = output or source`) and the independent findings write
# (effective target `findings`, only under `warn_on_mismatch`).
# ---------------------------------------------------------------------------

def _durable_fk_policy_frames(*, extra_columns: dict | None = None):
    """A sheet whose FK-attributed helper is named only by durable v2 relation
    policy -- no transient `_meta.derived` provenance of any kind."""
    row = {
        "id": "GROUP-0001",
        "home_place_id": "PLACE-0007",
        "_places_name": "Microraptorenwald",
    }
    row.update(extra_columns or {})
    return {
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
                        }
                    ],
                }
            }
        },
        "groups": pd.DataFrame([row]),
    }


def test_durable_policy_only_unauthorized_drop_emits_finding_under_warn_on_mismatch() -> None:
    """Durable-policy-only case #2 (required test matrix): the column is left
    in place, and `fk_deletion_unauthorized` is reported distinct from
    `derived_value_mismatch`."""
    frames = _durable_fk_policy_frames()

    out = apply_derived_column_policy(frames, source="groups", policy="warn_on_mismatch")

    assert "_places_name" in out["groups"].columns
    findings = out["derived_column_findings"]
    unauthorized = findings[findings["rule_type"] == "fk_deletion_unauthorized"]
    assert len(unauthorized) == 1
    row = unauthorized.iloc[0]
    assert row["columns"] == "_places_name"
    assert row["frame"] == "groups"
    assert row["severity"] == "warn"


def test_durable_policy_only_unauthorized_drop_does_not_raise_under_fail_on_mismatch() -> None:
    """Required test matrix #3: `fail_on_mismatch` must not gain permission to
    delete, and the authorization refusal itself must not become a new
    strictness exception."""
    frames = _durable_fk_policy_frames()

    out = apply_derived_column_policy(frames, source="groups", policy="fail_on_mismatch")

    assert "_places_name" in out["groups"].columns


def test_workbook_view_helper_columns_still_authorizes_cleanup_alongside_unrelated_durable_fk_policy() -> None:
    """Required test matrix #4: the separate, explicit Workbook-View
    `helper_columns` carrier still authorizes its own cleanup, unaffected by
    the durable FK relation policy's removal as deletion authority --
    proven here with both carriers present on the same sheet."""
    frames = _durable_fk_policy_frames()
    frames["_meta"]["sheets"] = {"groups": {"helper_columns": ["_places_name"]}}

    out = apply_derived_column_policy(frames, source="groups", policy="drop")

    assert "_places_name" not in out["groups"].columns


def test_workbook_view_authorized_removal_emits_no_false_fk_deletion_unauthorized() -> None:
    """FIND-S5-01 regression (independent Slice-5 review, Workbook-View
    variant): durable FK relation policy and Workbook-View
    `_meta.sheets[source].helper_columns` both name `_places_name`, with no
    transient FK provenance. Workbook-View authority correctly removes the
    column (as `test_workbook_view_helper_columns_still_authorizes_cleanup_...`
    already proves under `policy="drop"`), but under `warn_on_mismatch` the
    diagnostic used to be computed against the pre-drop payload and so fired
    a false `fk_deletion_unauthorized` for a column that was, in fact, no
    longer present in the returned frame at all. This fixture has no other
    unauthorized FK columns, so no findings of any kind are expected.

    This test fails against 2afb9f4 (the reviewed Slice-5 commit).
    """
    frames = _durable_fk_policy_frames()
    frames["_meta"]["sheets"] = {"groups": {"helper_columns": ["_places_name"]}}

    out = apply_derived_column_policy(frames, source="groups", policy="warn_on_mismatch")

    assert "_places_name" not in out["groups"].columns
    findings = out["derived_column_findings"]
    assert len(findings) == 0


def _durable_fk_policy_and_lookup_identity_frames():
    """`groups` where durable v2 FK relation policy and `groups`' own
    truthful, current `enrich_lookup` provenance both name `_places_name`,
    with no transient FK (`helper_columns`) provenance at all. The lookup
    values deliberately differ so the fixture also exercises a genuine
    `derived_value_mismatch` finding alongside the (absent, post-fix)
    authorization-refusal diagnostic."""
    groups = pd.DataFrame([
        {
            "id": "GROUP-0001",
            "home_place_id": "PLACE-0007",
            "_places_name": "Microraptorenwald",
        }
    ])
    places = pd.DataFrame([{"id": "PLACE-0007", "_places_name": "Old Forest"}])
    meta = {
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
                    }
                ],
            }
        },
        "derived": {
            "sheets": {
                "groups": {
                    "enrich_lookup": {
                        "lookup": "places",
                        "source_key": "home_place_id",
                        "lookup_key": "id",
                        "helper_columns": ["_places_name"],
                    }
                }
            }
        },
    }
    return {"_meta": meta, "groups": groups, "places": places}


def test_lookup_identity_authorized_removal_emits_no_false_fk_deletion_unauthorized() -> None:
    """FIND-S5-01 regression (independent Slice-5 review, Lookup-identity
    variant): durable FK relation policy names `_places_name`; `groups`' own
    truthful, current `enrich_lookup` provenance separately names the same
    physical label as its own helper column; no transient FK provenance
    exists at all. The column is legitimately dropped via Lookup's own
    declared identity, and the mismatched lookup value produces a genuine
    `derived_value_mismatch` finding -- but the diagnostic used to also
    falsely emit `fk_deletion_unauthorized` for the same, already-removed
    column because it checked the pre-drop payload rather than the returned
    frame.

    This test fails against 2afb9f4 (the reviewed Slice-5 commit).
    """
    frames = _durable_fk_policy_and_lookup_identity_frames()

    out = apply_derived_column_policy(frames, source="groups", policy="warn_on_mismatch")

    assert "_places_name" not in out["groups"].columns
    findings = out["derived_column_findings"]
    assert (findings["rule_type"] == "fk_deletion_unauthorized").sum() == 0
    mismatch = findings[findings["rule_type"] == "derived_value_mismatch"]
    assert len(mismatch) == 1
    assert mismatch.iloc[0]["columns"] == "_places_name"
    assert mismatch.iloc[0]["frame"] == "groups"


def test_payload_decoupled_target_invalidates_preexisting_provenance() -> None:
    """Repro 6 closure (FIND-D10): `apply_derived_column_policy(source=A,
    output=B, policy="drop")` where `B` already carries an FK
    `helper_columns` entry (and `A` carries its own, independently-sourced
    column under the same label) removes `B`'s stale entry as part of the
    same call; a subsequent cleanup pass over `B` leaves the (now
    `A`-owned) replacement column in place."""
    frames = {
        "_meta": {
            "derived": {
                "sheets": {
                    "B": {
                        "helper_columns": [
                            {
                                "column": "_Target_name",
                                "fk_column": "target_id",
                                "target": "targets",
                                "value_field": "name",
                            }
                        ]
                    }
                }
            }
        },
        "A": pd.DataFrame([{"id": 1, "_Target_name": "A-owned"}]),
        "B": pd.DataFrame([{"id": 1, "_Target_name": "B-fk-value"}]),
    }

    out = apply_derived_column_policy(frames, source="A", output="B", policy="drop")

    # Direct assertion: B's stale FK record is gone immediately.
    assert "B" not in out["_meta"].get("derived", {}).get("sheets", {})
    assert list(out["B"]["_Target_name"]) == ["A-owned"]

    # End-to-end: a later cleanup pass leaves the replacement's own values.
    cleaned = apply_derived_column_policy(out, source="B", policy="drop")
    assert "_Target_name" in cleaned["B"].columns
    assert list(cleaned["B"]["_Target_name"]) == ["A-owned"]


def test_payload_decoupled_new_frame_target_is_true_noop() -> None:
    """Over-invalidation guard (DCP): a brand-new `output` frame name has no
    pre-existing entry to invalidate and must not gain a meaningless
    `_meta` entry."""
    frames = {
        "_meta": {"derived": {"sheets": {}}},
        "A": pd.DataFrame([{"id": 1, "amount": 5}]),
    }

    out = apply_derived_column_policy(frames, source="A", output="brand_new", policy="drop")

    assert "brand_new" not in out["_meta"].get("derived", {}).get("sheets", {})


@pytest.mark.parametrize("output_value", ["", None])
def test_payload_output_empty_string_and_none_both_alias_to_source_target(output_value) -> None:
    """FIND-D13 Variant A closure: `output=""` must behave identically to
    `output=None` -- both resolve `payload_target = output or source` to
    `source` and strip source's own consumed provenance, unlike the pre-D13
    behavior which keyed lifecycle handling to raw `output`."""
    frames = {
        "_meta": {
            "derived": {
                "sheets": {
                    "A": {
                        "helper_columns": [
                            {
                                "column": "_B_name",
                                "fk_column": "b_id",
                                "target": "B",
                                "value_field": "name",
                            }
                        ]
                    }
                }
            },
            # Durable v2 policy is also present, matching a real
            # `configure_fk_helpers`/`add_fk_helpers` setup; it satisfies
            # `drop_helpers`'s unrelated "was FK policy configured at all"
            # precondition below and is never itself deletion authority.
            "helper_policies": {
                "fk": {
                    "schema_version": 2,
                    "relations": [
                        {
                            "source_frame": "A",
                            "source_column": "b_id",
                            "target_frame": "B",
                            "target_key": "id",
                            "helper_columns": [{"column": "_B_name", "target_field": "name"}],
                        }
                    ],
                }
            },
        },
        "A": pd.DataFrame([{"id": 1, "b_id": 10, "_B_name": "fk-value"}]),
    }

    out = apply_derived_column_policy(frames, source="A", output=output_value, policy="drop")

    assert "_B_name" not in out["A"].columns
    # Direct assertion: A's own stale FK record is invalidated too, not left
    # behind because the raw `output` value didn't equal `source` literally.
    assert "A" not in out["_meta"].get("derived", {}).get("sheets", {})

    # End-to-end wrongful-deletion sequence: a same-source enrich_lookup call
    # materializes Lookup's distinct values under the same label, writing its
    # own fresh, truthful `enrich_lookup` provenance for it; a later FK-only
    # cleanup pass (`drop_helpers`, which never reads the `enrich_lookup`
    # sibling subkey) must leave Lookup's values in place, not delete them
    # using A's now-invalidated FK record. (`apply_derived_column_policy`
    # itself would legitimately also remove this column at this point --
    # Lookup's own current, truthful declaration of its own artifact is
    # separately, intentionally droppable by DCP and is not part of this
    # defect's scope; `drop_helpers` isolates the FK-only claim.)
    lookup_frames = dict(out)
    lookup_frames["Lookup"] = pd.DataFrame([{"id": 1, "_B_name": "lookup-value"}])
    rebound = enrich_lookup(
        lookup_frames,
        source="A",
        lookup="Lookup",
        output="A",
        on="id",
        helpers={"fields": ["_B_name"]},
    )
    assert list(rebound["A"]["_B_name"]) == ["lookup-value"]

    cleaned = drop_helpers(rebound)
    assert "_B_name" in cleaned["A"].columns
    assert list(cleaned["A"]["_B_name"]) == ["lookup-value"]


def test_findings_publication_invalidates_preexisting_provenance_at_target() -> None:
    """FIND-D13 Variant B closure: the independent `findings` publication
    under `warn_on_mismatch` invalidates a pre-existing `_meta.derived.sheets`
    entry at its own target -- here `findings == source`, so the findings
    frame (with its own canonical `rule_type` column) physically replaces
    `A`, and a later cleanup pass must leave that canonical column alone
    rather than delete it using `A`'s stale FK record."""
    frames = {
        "_meta": {
            "derived": {
                "sheets": {
                    "A": {
                        "helper_columns": [
                            {
                                "column": "rule_type",
                                "fk_column": "b_id",
                                "target": "B",
                                "value_field": "type",
                            }
                        ]
                    }
                }
            }
        },
        "A": pd.DataFrame([{"id": 1, "b_id": 10, "rule_type": "fk-value", "amount": 5}]),
    }

    out = apply_derived_column_policy(
        frames, source="A", output="payload", findings="A", policy="warn_on_mismatch",
    )

    # payload is a brand-new target: no prior entry to invalidate there.
    assert "payload" in out
    # Direct assertion: A's stale FK record is invalidated by the findings
    # write, even though the payload write's own branch had no reason to
    # touch A (payload_target="payload" != source="A" != A's own name here).
    assert "A" not in out["_meta"].get("derived", {}).get("sheets", {})
    assert list(out["A"].columns) == FINDING_COLUMNS

    cleaned = apply_derived_column_policy(out, source="A", policy="drop")
    assert "rule_type" in cleaned["A"].columns


def test_findings_equals_payload_target_publication_order_leaves_no_stale_provenance() -> None:
    """Publication-order boundary case: `findings == payload_target`. The
    payload write's own invalidation strips the shared target first; the
    findings write then physically overwrites it a second time and its own
    invalidation re-checks the now-current metadata, finding nothing left
    (a safe, idempotent no-op). The findings frame is the final physical
    writer, and no stale provenance survives either way."""
    frames = {
        "_meta": {
            "derived": {
                "sheets": {
                    "B": {
                        "enrich_lookup": {
                            "lookup": "Other",
                            "on": ["id"],
                            "helper_columns": ["foreign_col"],
                        }
                    }
                }
            }
        },
        "A": pd.DataFrame([{"id": 1, "amount": 5}]),
        "B": pd.DataFrame([{"id": 1, "foreign_col": "keep-me-if-bug"}]),
    }

    out = apply_derived_column_policy(
        frames, source="A", output="B", findings="B", policy="warn_on_mismatch",
    )

    assert "B" not in out["_meta"].get("derived", {}).get("sheets", {})
    assert list(out["B"].columns) == FINDING_COLUMNS


def test_decoupled_payload_invalidation_preserves_unrelated_meta_and_sheets() -> None:
    """No unrelated provenance damage: a sibling sheet's own provenance and
    unrelated top-level `_meta` roots survive target-local invalidation
    untouched."""
    frames = {
        "_meta": {
            "derived": {
                "sheets": {
                    "B": {
                        "helper_columns": [
                            {
                                "column": "_Target_name",
                                "fk_column": "target_id",
                                "target": "targets",
                                "value_field": "name",
                            }
                        ]
                    },
                    "C": {
                        "enrich_lookup": {
                            "lookup": "Other",
                            "on": ["id"],
                            "helper_columns": ["sibling_col"],
                        }
                    },
                }
            },
            "helper_policies": {"fk": {"schema_version": 2, "relations": []}},
        },
        "A": pd.DataFrame([{"id": 1, "_Target_name": "A-owned"}]),
        "B": pd.DataFrame([{"id": 1, "_Target_name": "B-fk-value"}]),
        "C": pd.DataFrame([{"id": 1, "sibling_col": "keep"}]),
    }

    out = apply_derived_column_policy(frames, source="A", output="B", policy="drop")

    assert "B" not in out["_meta"]["derived"]["sheets"]
    assert out["_meta"]["derived"]["sheets"]["C"] == frames["_meta"]["derived"]["sheets"]["C"]
    assert out["_meta"]["helper_policies"] == frames["_meta"]["helper_policies"]
    assert list(out["C"]["sibling_col"]) == ["keep"]


def test_dcp_and_drop_helpers_agree_durable_policy_alone_is_not_authority() -> None:
    """Direct executor parity (required test matrix #14): DCP and
    `drop_helpers` now agree that durable FK relation intent alone is never
    deletion authority."""
    def _frames():
        return _durable_fk_policy_frames()

    dcp_out = apply_derived_column_policy(_frames(), source="groups", policy="drop")
    drop_out = drop_helpers(_frames())

    assert "_places_name" in dcp_out["groups"].columns
    assert "_places_name" in drop_out["groups"].columns
