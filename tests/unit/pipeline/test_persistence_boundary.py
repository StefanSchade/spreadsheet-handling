"""Unit tests for the orchestrator's persistence-boundary projection.

Scope reflects the narrow rules established by
BUG-RUNTIME-META-PERSISTENCE-BOUNDARY-P4A:

* drop top-level ``derived``,
* drop top-level ``__*``-prefixed keys,
* drop ``helper_policies.fk.relations`` entries where
  ``produced_by.step == configure_fk_helpers``,
* preserve everything else.

A complete ``_meta`` lifecycle inventory is intentionally out of scope. See
``FTR-META-LIFECYCLE-INVENTORY-P5`` for the broader follow-up.
"""

from __future__ import annotations

import copy

import pytest

from spreadsheet_handling.pipeline.persistence_boundary import (
    project_meta_to_persistable_contract,
)


pytestmark = pytest.mark.ftr("BUG-RUNTIME-META-PERSISTENCE-BOUNDARY-P4A")


def test_drops_top_level_derived() -> None:
    meta = {
        "version": "1.0",
        "derived": {"sheets": {"groups": {"helper_columns": []}}},
    }
    out = project_meta_to_persistable_contract(meta)
    assert "derived" not in out
    assert out["version"] == "1.0"


def test_drops_top_level_dunder_keys() -> None:
    meta = {
        "freeze_header": True,
        "__style": {"some": "carrier"},
        "__autofilter_ref": "A1:B2",
    }
    out = project_meta_to_persistable_contract(meta)
    assert "__style" not in out
    assert "__autofilter_ref" not in out
    assert out["freeze_header"] is True


def test_keeps_helper_policies_v1_per_target_dicts() -> None:
    meta = {
        "helper_policies": {
            "fk": {
                "places": {
                    "allowed_helpers": ["name"],
                    "target": "places",
                },
            },
        },
    }
    out = project_meta_to_persistable_contract(meta)
    assert out["helper_policies"]["fk"]["places"]["target"] == "places"


def test_keeps_relations_without_runtime_produced_marker() -> None:
    meta = {
        "helper_policies": {
            "fk": {
                "schema_version": 2,
                "relations": [
                    {
                        "source_frame": "characters",
                        "source_column": "home_place_id",
                        "target_frame": "places",
                        "target_key": "id",
                        "helper_columns": [{"column": "_places_name"}],
                    },
                ],
            },
        },
    }
    out = project_meta_to_persistable_contract(meta)
    relations = out["helper_policies"]["fk"]["relations"]
    assert len(relations) == 1
    assert relations[0]["source_frame"] == "characters"
    assert out["helper_policies"]["fk"]["schema_version"] == 2


def test_drops_runtime_produced_fk_helper_relations() -> None:
    meta = {
        "helper_policies": {
            "fk": {
                "schema_version": 2,
                "relations": [
                    {
                        "source_frame": "groups",
                        "target_frame": "places",
                        "produced_by": {"mode": "explicit", "step": "configure_fk_helpers"},
                    },
                    {
                        "source_frame": "characters",
                        "target_frame": "places",
                        "produced_by": {"mode": "user_authored", "step": "manual"},
                    },
                ],
            },
        },
    }
    out = project_meta_to_persistable_contract(meta)
    kept = out["helper_policies"]["fk"]["relations"]
    assert len(kept) == 1
    assert kept[0]["source_frame"] == "characters"


def test_drops_empty_relations_and_schema_version_after_full_prune() -> None:
    """If every relation was runtime-produced, drop the empty marker plus the
    schema_version that only describes the relations envelope."""
    meta = {
        "helper_policies": {
            "fk": {
                "schema_version": 2,
                "relations": [
                    {
                        "source_frame": "groups",
                        "target_frame": "places",
                        "produced_by": {"step": "configure_fk_helpers"},
                    },
                ],
                "places": {"target": "places"},  # v1 entry must survive
            },
        },
    }
    out = project_meta_to_persistable_contract(meta)
    fk = out["helper_policies"]["fk"]
    assert "relations" not in fk
    assert "schema_version" not in fk
    assert fk["places"]["target"] == "places"


def test_keeps_helper_policies_lookup_namespace() -> None:
    meta = {
        "helper_policies": {
            "lookup": {
                "places": {"allowed_helpers": ["name"]},
            },
        },
    }
    out = project_meta_to_persistable_contract(meta)
    assert out["helper_policies"]["lookup"]["places"]["allowed_helpers"] == ["name"]


def test_projection_is_idempotent() -> None:
    meta = {
        "derived": {"sheets": {}},
        "helper_policies": {
            "fk": {
                "schema_version": 2,
                "relations": [
                    {"source_frame": "groups", "produced_by": {"step": "configure_fk_helpers"}},
                ],
            },
        },
        "freeze_header": True,
    }
    first = project_meta_to_persistable_contract(meta)
    second = project_meta_to_persistable_contract(first)
    assert first == second


def test_does_not_mutate_input() -> None:
    meta = {
        "derived": {"x": 1},
        "helper_policies": {
            "fk": {
                "relations": [
                    {"source_frame": "groups", "produced_by": {"step": "configure_fk_helpers"}},
                ],
            },
        },
    }
    snapshot = copy.deepcopy(meta)
    project_meta_to_persistable_contract(meta)
    assert meta == snapshot


def test_handles_none_and_empty_meta() -> None:
    assert project_meta_to_persistable_contract(None) == {}
    assert project_meta_to_persistable_contract({}) == {}


def test_handles_non_mapping_helper_policies_value_gracefully() -> None:
    """Pure-function robustness: a malformed helper_policies that isn't a
    mapping is passed through unchanged so the projection cannot crash on
    unexpected input shapes."""
    meta = {"helper_policies": "garbage"}
    out = project_meta_to_persistable_contract(meta)
    assert out == {"helper_policies": "garbage"}
