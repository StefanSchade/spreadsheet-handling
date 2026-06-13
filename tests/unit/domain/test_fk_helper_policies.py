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


def test_configure_fk_helpers_writes_resolved_v2_relation() -> None:
    # FK Helper Slice 2: configure_fk_helpers writes only the durable v2
    # relation model; the legacy v1 per-target dict is no longer persisted.
    # The resolved policy (key, allowed/default helpers, fk_column convention)
    # is still validated and is reflected in the v2 relation it produces.
    frames = _frames()
    frames["Orders"] = pd.DataFrame({"order_id": ["o1", "o2"], "id_(Products)": ["p1", "p2"]})
    out = configure_fk_helpers(
        frames,
        target="Products",
        key="id",
        allowed_helpers=["name", "category"],
        default_helpers=["category"],
        fk_columns={"convention": "{key}_({target})"},
    )

    fk_root = out["_meta"]["helper_policies"]["fk"]
    assert "Products" not in fk_root  # no v1 per-target dict
    assert fk_root["schema_version"] == 2
    relation = fk_root["relations"][0]
    assert relation["source_frame"] == "Orders"
    assert relation["source_column"] == "id_(Products)"
    assert relation["target_frame"] == "Products"
    assert relation["target_key"] == "id"
    assert relation["helper_columns"] == [
        {"column": "_Products_category", "target_field": "category"}
    ]
    assert relation["produced_by"] == {"step": "configure_fk_helpers", "mode": "explicit"}


def test_configure_fk_helpers_rejects_targets_auto_with_migration_message() -> None:
    with pytest.raises(ValueError, match="infer_fk_relations"):
        configure_fk_helpers(
            _frames(),
            targets="auto",
            auto={"id_column_candidates": ["id"]},
        )


def test_configure_fk_helpers_emits_durable_v2_relation() -> None:
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
    assert "Products" not in fk_root  # FK Helper Slice 2: no v1 per-target dict
    relations = fk_root["relations"]
    assert len(relations) == 1
    relation = relations[0]
    assert relation["source_frame"] == "Orders"
    assert relation["source_column"] == "id_(Products)"
    assert relation["target_frame"] == "Products"
    assert relation["target_key"] == "id"
    assert relation["helper_columns"] == [
        {"column": "_Products_name", "target_field": "name"}
    ]
    assert relation["produced_by"] == {
        "step": "configure_fk_helpers",
        "mode": "explicit",
    }


def test_configure_fk_helpers_accepts_targets_mapping() -> None:
    frames = _frames()
    frames["Orders"] = pd.DataFrame({"id_(Products)": ["p1", "p2"]})
    out = configure_fk_helpers(
        frames,
        targets={
            "Products": {
                "key": "id",
                "allowed_helpers": ["name", "category"],
                "default_helpers": ["name"],
            }
        },
    )

    # FK Helper Slice 2: the resolved default_helpers surface as the v2
    # relation's helper_columns (no v1 per-target dict is written).
    relation = out["_meta"]["helper_policies"]["fk"]["relations"][0]
    assert relation["target_frame"] == "Products"
    assert relation["helper_columns"] == [{"column": "_Products_name", "target_field": "name"}]


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


# ----- v2 relation identity derivation inside configure_fk_helpers -----------
#
# The v2 entries for the explicit/manual path are derived by deterministic
# scan: every data frame that carries the configured literal ``fk_column``
# header gets one v2 relation entry, keyed by ``(source_frame, source_column)``.
# This is deterministic identity derivation, not heuristic inference (which is
# owned by ``infer_fk_relations``).


def test_configure_fk_helpers_is_noop_when_no_frame_carries_fk_column() -> None:
    # The target frame exists but no source frame carries the configured
    # `fk_column`. FK Helper Slice 2: the v1 per-target dict is retired and no
    # v2 relation can be derived, so configure persists nothing for FK helpers.
    out = configure_fk_helpers(
        _frames(),
        target="Products",
        key="id",
        allowed_helpers=["name"],
        default_helpers=["name"],
        fk_column="id_(Products)",  # no other frame carries this column
    )

    fk_root = ((out.get("_meta") or {}).get("helper_policies") or {}).get("fk") or {}
    assert "Products" not in fk_root  # no v1 per-target dict
    assert "relations" not in fk_root  # no v2 relation derived
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


def test_configure_then_enrich_materializes_via_v2() -> None:
    # configure_fk_helpers writes the durable v2 relation; the enrich primitive
    # consumes that v2 relation and materializes helper columns.
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

    # FK Helper Slice 2: durable v2 only, no v1 per-target dict.
    fk_root = after_configure["_meta"]["helper_policies"]["fk"]
    assert "Products" not in fk_root
    assert fk_root["schema_version"] == 2
    assert len(fk_root["relations"]) == 1

    # The primitive consumes the v2 relation and writes helper columns.
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
