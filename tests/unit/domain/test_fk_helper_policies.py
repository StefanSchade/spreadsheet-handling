from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.helper_policies import configure_fk_helpers


pytestmark = [
    pytest.mark.ftr("FTR-FK-HELPER-CONFIGURATION-STEPS-P4"),
    pytest.mark.ftr("FTR-INFER-FK-RELATIONS-CONFIGURATION-STEP-P5"),
]


def _frames() -> dict:
    return {
        "Products": pd.DataFrame(
            {
                "id": ["p1", "p2"],
                "name": ["Alpha", "Beta"],
                "category": ["A", "B"],
                "sort_key": [2, 1],
                "active": [True, False],
            }
        )
    }


def test_configure_fk_helpers_writes_resolved_target_policy() -> None:
    out = configure_fk_helpers(
        _frames(),
        target="Products",
        key="id",
        allowed_helpers=["name", "category"],
        default_helpers=["category"],
        fk_columns={"convention": "{key}_({target})"},
    )

    policy = out["_meta"]["helper_policies"]["fk"]["Products"]
    assert policy == {
        "target": "Products",
        "target_sheet": "Products",
        "key": "id",
        "allowed_helpers": ["name", "category"],
        "default_helpers": ["category"],
        "helper_prefix": "_",
        "fk_column": "id_(Products)",
    }


def test_configure_fk_helpers_rejects_targets_auto_with_migration_message() -> None:
    with pytest.raises(ValueError, match="infer_fk_relations"):
        configure_fk_helpers(
            _frames(),
            targets="auto",
            auto={"id_column_candidates": ["id"]},
        )


def test_configure_fk_helpers_emits_v2_marker_alongside_v1_keys() -> None:
    frames = _frames()
    frames["Orders"] = pd.DataFrame(
        {
            "order_id": ["o1", "o2"],
            "id_(Products)": ["p1", "p2"],
        }
    )
    out = configure_fk_helpers(
        frames,
        target="Products",
        key="id",
        allowed_helpers=["name"],
        default_helpers=["name"],
    )

    fk_root = out["_meta"]["helper_policies"]["fk"]
    assert fk_root["schema_version"] == 2
    assert "Products" in fk_root  # v1 per-target dict still present
    relations = fk_root["relations"]
    assert len(relations) == 1
    relation = relations[0]
    assert relation["source_frame"] == "Orders"
    assert relation["source_column"] == "id_(Products)"
    assert relation["target_frame"] == "Products"
    assert relation["target_key"] == "id"
    assert relation["helper_fields"] == ["name"]
    assert relation["helper_columns"] == [
        {"column": "_Products_name", "target_field": "name"}
    ]
    assert relation["produced_by"] == {
        "step": "configure_fk_helpers",
        "mode": "explicit",
    }


def test_configure_fk_helpers_accepts_targets_mapping() -> None:
    out = configure_fk_helpers(
        _frames(),
        targets={
            "Products": {
                "key": "id",
                "allowed_helpers": ["name", "category"],
                "default_helpers": ["name"],
            }
        },
    )

    assert out["_meta"]["helper_policies"]["fk"]["Products"]["default_helpers"] == ["name"]


def test_configure_fk_helpers_rejects_defaults_outside_allowlist() -> None:
    with pytest.raises(ValueError, match="must be included in allowed_helpers"):
        configure_fk_helpers(
            _frames(),
            target="Products",
            key="id",
            allowed_helpers=["name"],
            default_helpers=["category"],
        )


def test_configure_fk_helpers_rejects_unknown_target_helper_columns() -> None:
    with pytest.raises(KeyError, match="not found in target frame"):
        configure_fk_helpers(
            _frames(),
            target="Products",
            key="id",
            allowed_helpers=["name", "missing"],
            default_helpers=["name"],
        )


# ----- v1 -> v2 transitional bridge inside configure_fk_helpers --------------
#
# The v2 entries for the explicit/manual path are derived by deterministic
# scan: every data frame that carries the configured literal ``fk_column``
# header gets one v2 relation entry, keyed by ``(source_frame, source_column)``.
# This is a documented transitional compatibility bridge; the primitives FTR
# (FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5) owns narrowing or removing it.


def test_configure_fk_helpers_bridge_writes_no_v2_when_no_frame_carries_fk_column() -> None:
    # The target frame exists but no source frame carries the configured
    # `fk_column`; v1 must still be written, v2 must contain only the
    # schema_version marker and an empty `relations` list.
    out = configure_fk_helpers(
        _frames(),
        target="Products",
        key="id",
        allowed_helpers=["name"],
        default_helpers=["name"],
        fk_column="id_(Products)",  # no other frame carries this column
    )

    fk_root = out["_meta"]["helper_policies"]["fk"]
    assert "Products" in fk_root  # v1 per-target dict written
    # Bridge emitted no v2 relation because no source frame carries the FK col.
    assert "relations" not in fk_root
    assert "schema_version" not in fk_root


def test_configure_fk_helpers_bridge_writes_one_v2_per_source_frame() -> None:
    # Two source frames both carry the same configured `fk_column`. Relation
    # identity is per (source_frame, source_column), so the bridge writes one
    # v2 entry per source frame.
    frames = _frames()
    frames["Orders"] = pd.DataFrame({"id_(Products)": ["p1"]})
    frames["Returns"] = pd.DataFrame({"id_(Products)": ["p2"]})

    out = configure_fk_helpers(
        frames,
        target="Products",
        key="id",
        allowed_helpers=["name"],
        default_helpers=["name"],
    )

    relations = out["_meta"]["helper_policies"]["fk"]["relations"]
    keys = {(r["source_frame"], r["source_column"]) for r in relations}
    assert keys == {
        ("Orders", "id_(Products)"),
        ("Returns", "id_(Products)"),
    }
    # All entries record the same producer and target.
    producers = {r["produced_by"]["step"] for r in relations}
    assert producers == {"configure_fk_helpers"}
    target_frames = {r["target_frame"] for r in relations}
    assert target_frames == {"Products"}


def test_configure_fk_helpers_bridge_coexists_with_v1_primitive_consumption() -> None:
    # The bridge writes v2 alongside v1; v2 must not break the v1 primitive
    # consumer in the existing fk_helpers package.
    from spreadsheet_handling.domain.transformations.fk_helpers import enrich_helpers

    frames = _frames()
    frames["Orders"] = pd.DataFrame(
        {
            "order_id": ["o1", "o2"],
            "id_(Products)": ["p1", "p2"],
        }
    )

    after_configure = configure_fk_helpers(
        frames,
        target="Products",
        key="id",
        allowed_helpers=["name"],
        default_helpers=["name"],
    )

    # Confirm both shapes exist after configure step.
    fk_root = after_configure["_meta"]["helper_policies"]["fk"]
    assert "Products" in fk_root
    assert fk_root["schema_version"] == 2
    assert len(fk_root["relations"]) == 1

    # v1 primitive consumes the v1 per-target shape and writes helper columns.
    out = enrich_helpers(after_configure, {})
    helper_columns = [
        column[0] if isinstance(column, tuple) else column
        for column in out["Orders"].columns
    ]
    assert "_Products_name" in helper_columns
    # v2 view is preserved through the primitive (the primitive does not strip it).
    after_fk_root = out["_meta"]["helper_policies"]["fk"]
    assert after_fk_root["schema_version"] == 2
    assert len(after_fk_root["relations"]) == 1
