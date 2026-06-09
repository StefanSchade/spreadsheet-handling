"""Unit tests for the orchestrator's persistence-boundary projection.

Scope reflects the narrow rules established by
BUG-RUNTIME-META-PERSISTENCE-BOUNDARY-P4A and extended by
BUG-CROSS-CARRIER-META-ROUNDTRIP-P4A (Intent vs Resolution slice):

* drop top-level ``derived``,
* drop top-level ``__*``-prefixed keys,
* drop ``helper_policies.fk.relations`` entries where
  ``produced_by.step == configure_fk_helpers``,
* drop ``legend_blocks[*].resolved`` (Resolution under canonical),
* drop ``xref_crosstable[*].dense_axes.resolved`` (Resolution),
* drop ``xref_crosstable[*].column_keys`` (Resolution),
* preserve everything else (including ``source: workbook`` provenance).

A complete ``_meta`` lifecycle inventory is intentionally out of scope. See
``FTR-META-LIFECYCLE-INVENTORY-P5`` for the broader follow-up.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from spreadsheet_handling.pipeline.persistence_boundary import (
    project_meta_to_persistable_contract,
)


pytestmark = pytest.mark.ftr("BUG-RUNTIME-META-PERSISTENCE-BOUNDARY-P4A")


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "backlog"
    / "fixtures"
    / "BUG-CROSS-CARRIER-META-ROUNDTRIP"
    / "ods_produced_meta.yaml"
)


def _load_ods_produced_meta_fixture() -> dict:
    with _FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return loaded


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


# ---------------------------------------------------------------------------
# BUG-CROSS-CARRIER-META-ROUNDTRIP-P4A -- Intent vs Resolution slice
# ---------------------------------------------------------------------------


@pytest.mark.ftr("BUG-CROSS-CARRIER-META-ROUNDTRIP-P4A")
class TestIntentVsResolutionSlice:
    """Persist Intent; drop the three named Resolution facets only."""

    def test_drops_legend_blocks_resolved_facet(self) -> None:
        meta = {
            "legend_blocks": {
                "story_group_codes": {
                    "title": "Story Group Codes",
                    "entries": [{"label": "Central role", "token": "C"}],
                    "placement": {
                        "anchor": "right_of_table",
                        "sheet": "story_groups",
                        "target": "story_groups",
                    },
                    "resolved": {
                        "frame_name": "legend_story_group_codes",
                        "kind": "legend",
                        "left": 12,
                        "n_cols": 3,
                        "n_rows": 3,
                        "sheet": "story_groups",
                        "top": 1,
                    },
                },
            },
        }

        out = project_meta_to_persistable_contract(meta)
        block = out["legend_blocks"]["story_group_codes"]

        assert "resolved" not in block
        assert block["title"] == "Story Group Codes"
        assert block["placement"]["anchor"] == "right_of_table"
        assert block["entries"][0]["token"] == "C"

    def test_drops_xref_crosstable_column_keys_facet(self) -> None:
        meta = {
            "xref_crosstable": {
                "story_cast_crystal_named": {
                    "column_key": "character_name",
                    "column_keys": ["Tim", "Galli", "Comphi"],
                    "row_keys": ["story_id"],
                    "relation": "story_cast_crystal_named",
                    "value": "value",
                    "drop_empty": True,
                    "matrix": "story_cast_crystal_matrix_payload",
                    "operation": "expand_xref",
                },
            },
        }

        out = project_meta_to_persistable_contract(meta)
        entry = out["xref_crosstable"]["story_cast_crystal_named"]

        assert "column_keys" not in entry
        assert entry["column_key"] == "character_name"
        assert entry["row_keys"] == ["story_id"]
        assert entry["relation"] == "story_cast_crystal_named"
        assert entry["operation"] == "expand_xref"

    def test_drops_xref_dense_axes_resolved_facet_but_keeps_intent(self) -> None:
        meta = {
            "xref_crosstable": {
                "story_cast_crystal_named": {
                    "column_key": "character_name",
                    "row_keys": ["story_id"],
                    "dense_axes": {
                        "columns_from": {"frame": "characters", "key": "name"},
                        "rows_from": {"frame": "stories", "key": "id"},
                        "resolved": {
                            "column_keys": ["Tim", "Galli"],
                            "row_identities": [
                                {"story_id": "STORY-0001"},
                                {"story_id": "STORY-0002"},
                            ],
                        },
                    },
                },
            },
        }

        out = project_meta_to_persistable_contract(meta)
        dense_axes = out["xref_crosstable"]["story_cast_crystal_named"]["dense_axes"]

        assert "resolved" not in dense_axes
        assert dense_axes["columns_from"] == {"frame": "characters", "key": "name"}
        assert dense_axes["rows_from"] == {"frame": "stories", "key": "id"}

    def test_captured_fixture_loses_three_resolution_facets(self) -> None:
        """Architecture-style fixture check: loading the captured
        ODS-produced sidecar through the persistence boundary strips the
        three named Resolution facets but leaves Intent intact."""
        fixture = _load_ods_produced_meta_fixture()

        # Sanity: the fixture contains the facets we claim to prune.
        assert "resolved" in fixture["legend_blocks"]["story_group_codes"]
        any_xref = next(iter(fixture["xref_crosstable"].values()))
        assert "column_keys" in any_xref
        assert "resolved" in any_xref["dense_axes"]

        out = project_meta_to_persistable_contract(fixture)

        for block in out["legend_blocks"].values():
            assert "resolved" not in block, (
                "legend_blocks[*].resolved must not survive the persistence "
                f"boundary; got keys {sorted(block)}"
            )
        for entry in out["xref_crosstable"].values():
            assert "column_keys" not in entry, (
                "xref_crosstable[*].column_keys must not survive the "
                f"persistence boundary; got keys {sorted(entry)}"
            )
            dense_axes = entry.get("dense_axes")
            if isinstance(dense_axes, dict):
                assert "resolved" not in dense_axes, (
                    "xref_crosstable[*].dense_axes.resolved must not survive "
                    f"the persistence boundary; got keys {sorted(dense_axes)}"
                )

    def test_captured_fixture_preserves_intent_fields(self) -> None:
        """Positive checks: Intent and Provenance survive the boundary."""
        fixture = _load_ods_produced_meta_fixture()
        out = project_meta_to_persistable_contract(fixture)

        # Top-level Intent.
        assert out["workbook_view"] == fixture["workbook_view"]
        assert out["auto_filter"] == fixture["auto_filter"]
        assert out["freeze_header"] == fixture["freeze_header"]
        assert out["helper_prefix"] == fixture["helper_prefix"]
        assert out["constraints"] == fixture["constraints"]
        assert out["cell_codecs"] == fixture["cell_codecs"]
        assert out["compact_multiaxis"] == fixture["compact_multiaxis"]
        assert out["split_by_discriminator"] == fixture["split_by_discriminator"]
        # frame_lifecycle and source: workbook are intentionally not pruned
        # in this slice; verify they pass through unchanged.
        assert out["frame_lifecycle"] == fixture["frame_lifecycle"]
        sheets = out["sheets"]
        any_sheet = next(iter(sheets.values()))
        any_width = next(iter(any_sheet["column_widths"].values()))
        assert any_width.get("source") == "workbook"

        # legend_blocks Intent fields survive.
        legend = out["legend_blocks"]["story_group_codes"]
        assert legend["title"] == "Story Group Codes"
        assert legend["entries"] == fixture["legend_blocks"]["story_group_codes"]["entries"]
        assert legend["placement"] == fixture["legend_blocks"]["story_group_codes"]["placement"]

        # xref_crosstable Intent fields survive.
        for name, entry in out["xref_crosstable"].items():
            source = fixture["xref_crosstable"][name]
            for intent_key in (
                "column_key",
                "row_keys",
                "relation",
                "matrix",
                "operation",
                "drop_empty",
                "value",
            ):
                if intent_key in source:
                    assert entry[intent_key] == source[intent_key]
            dense_axes = entry.get("dense_axes")
            if isinstance(dense_axes, dict):
                src_dense = source["dense_axes"]
                assert dense_axes["columns_from"] == src_dense["columns_from"]
                assert dense_axes["rows_from"] == src_dense["rows_from"]

    def test_handles_non_mapping_legend_blocks_and_xref_crosstable(self) -> None:
        """Robustness: unexpected shapes pass through unchanged rather than
        crashing the projection."""
        meta = {"legend_blocks": "garbage", "xref_crosstable": ["x"]}
        out = project_meta_to_persistable_contract(meta)
        assert out["legend_blocks"] == "garbage"
        assert out["xref_crosstable"] == ["x"]

    def test_does_not_mutate_legend_blocks_or_xref_crosstable(self) -> None:
        meta = {
            "legend_blocks": {
                "x": {"title": "T", "resolved": {"left": 0}},
            },
            "xref_crosstable": {
                "y": {
                    "column_key": "k",
                    "column_keys": ["a"],
                    "dense_axes": {
                        "columns_from": {"frame": "f", "key": "k"},
                        "resolved": {"column_keys": ["a"]},
                    },
                },
            },
        }
        snapshot = copy.deepcopy(meta)
        project_meta_to_persistable_contract(meta)
        assert meta == snapshot
