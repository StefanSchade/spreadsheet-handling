"""Unit tests for the domain ingress Legend Blocks shape-normalization rule.

Covers the FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5 shape contract:
absent root no-op, explicit-None canonicalization, mapping preservation,
list-to-ordered-mapping conversion, name/id/positional identity, empty list,
malformed members, duplicate identities, unsupported root, ``resolved``
pruning, immutability, and atomic failure. Entry-value policy is intentionally
untouched (that is the sibling FTR-LEGEND-BLOCKS-ENTRY-CONTRACT-P5's scope).
"""

from __future__ import annotations

import copy

import pytest

from spreadsheet_handling.domain.ingress import (
    INGRESS_RULES,
    run_domain_ingress,
)

pytestmark = pytest.mark.ftr(
    ["FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5", "FTR-TRUSTED-INGRESS-P4A"]
)


def _legend(frames: dict) -> dict:
    return frames["_meta"]["legend_blocks"]


# --- no-op / absent root ---------------------------------------------------


def test_absent_meta_is_noop():
    # No top-level carrier at all (beyond the absent `_meta`) so the fixture
    # also satisfies E2 ordinary structural admission, now wired into
    # `run_domain_ingress` by Phase-E slice E5; an arbitrary opaque object
    # would (correctly) be rejected before this rule ever runs.
    frames: dict = {}
    assert run_domain_ingress(frames) is frames


def test_absent_legend_blocks_root_is_noop():
    frames = {"_meta": {"constraints": []}}
    assert run_domain_ingress(frames) is frames


def test_none_legend_blocks_root_becomes_empty_mapping_without_input_mutation():
    frames = {"_meta": {"legend_blocks": None}}
    out = run_domain_ingress(frames)
    assert out["_meta"]["legend_blocks"] == {}
    assert frames == {"_meta": {"legend_blocks": None}}
    assert out is not frames
    assert out["_meta"] is not frames["_meta"]


# --- mapping preservation --------------------------------------------------


def test_mapping_form_is_preserved_value_and_order():
    frames = {
        "_meta": {
            "legend_blocks": {
                "b": {"title": "B", "entries": [{"token": "B"}]},
                "a": {"title": "A", "entries": [{"token": "A"}]},
            }
        }
    }
    out = run_domain_ingress(frames)
    blocks = _legend(out)
    assert list(blocks) == ["b", "a"]  # insertion order preserved
    assert list(blocks["b"]) == ["title", "entries"]  # field order preserved
    assert blocks["a"]["entries"] == [{"token": "A"}]


def test_empty_mapping_stays_empty_mapping():
    out = run_domain_ingress({"_meta": {"legend_blocks": {}}})
    assert _legend(out) == {}


# --- list conversion and identity -----------------------------------------


def test_list_form_normalizes_to_ordered_mapping():
    frames = {
        "_meta": {
            "legend_blocks": [
                {"name": "status", "entries": [{"token": "A"}]},
                {"id": "codes", "entries": [{"token": "B"}]},
                {"entries": [{"token": "C"}]},
            ]
        }
    }
    out = run_domain_ingress(frames)
    blocks = _legend(out)
    assert list(blocks) == ["status", "codes", "legend_3"]
    # Block mapping preserved (identity field kept), entries untouched.
    assert blocks["status"] == {"name": "status", "entries": [{"token": "A"}]}
    assert blocks["codes"] == {"id": "codes", "entries": [{"token": "B"}]}
    assert blocks["legend_3"] == {"entries": [{"token": "C"}]}


def test_identity_prefers_name_over_id_over_position():
    frames = {
        "_meta": {"legend_blocks": [{"name": "n", "id": "i", "entries": [{"token": "A"}]}]}
    }
    assert list(_legend(run_domain_ingress(frames))) == ["n"]


def test_identity_truthiness_falls_through_empty_values():
    # Empty name/id are falsy -> positional fallback, matching str(... or ...).
    frames = {"_meta": {"legend_blocks": [{"name": "", "id": "", "entries": []}]}}
    assert list(_legend(run_domain_ingress(frames))) == ["legend_1"]


def test_empty_list_becomes_empty_mapping():
    out = run_domain_ingress({"_meta": {"legend_blocks": []}})
    assert _legend(out) == {}


# --- failures --------------------------------------------------------------


def test_non_mapping_list_member_fails_with_position():
    with pytest.raises(ValueError, match="position 2"):
        run_domain_ingress({"_meta": {"legend_blocks": [{"name": "ok"}, 5]}})


def test_duplicate_explicit_identity_fails():
    with pytest.raises(ValueError, match="duplicate legend block identity 'x'"):
        run_domain_ingress(
            {"_meta": {"legend_blocks": [{"name": "x"}, {"name": "x"}]}}
        )


def test_positional_collision_with_explicit_identity_fails():
    # An explicit "legend_2" collides with the positional fallback of item 2.
    with pytest.raises(ValueError, match="duplicate legend block identity 'legend_2'"):
        run_domain_ingress(
            {"_meta": {"legend_blocks": [{"name": "legend_2"}, {"entries": []}]}}
        )


@pytest.mark.parametrize("bad_root", ["x", 5, 3.0, True])
def test_unsupported_root_fails(bad_root):
    with pytest.raises(ValueError, match="must be a mapping or a list"):
        run_domain_ingress({"_meta": {"legend_blocks": bad_root}})


# --- resolved pruning ------------------------------------------------------


def test_resolved_is_stripped_from_mapping_form():
    frames = {
        "_meta": {
            "legend_blocks": {
                "s": {"entries": [{"token": "A"}], "resolved": {"top": 1, "left": 5}}
            }
        }
    }
    block = _legend(run_domain_ingress(frames))["s"]
    assert "resolved" not in block
    assert block == {"entries": [{"token": "A"}]}


def test_resolved_is_stripped_from_list_form():
    frames = {
        "_meta": {
            "legend_blocks": [
                {"name": "s", "entries": [{"token": "A"}], "resolved": {"top": 1}}
            ]
        }
    }
    assert "resolved" not in _legend(run_domain_ingress(frames))["s"]


# --- immutability / atomic failure -----------------------------------------


def test_success_does_not_mutate_caller_input():
    frames = {
        "_meta": {
            "legend_blocks": [
                {"name": "s", "entries": [{"token": "A"}], "resolved": {"top": 1}}
            ]
        }
    }
    before = copy.deepcopy(frames)
    out = run_domain_ingress(frames)
    assert frames == before  # caller graph untouched
    assert out is not frames
    assert out["_meta"] is not frames["_meta"]


def test_failure_does_not_mutate_caller_input():
    frames = {"_meta": {"legend_blocks": [{"name": "dup"}, {"name": "dup"}]}}
    before = copy.deepcopy(frames)
    with pytest.raises(ValueError):
        run_domain_ingress(frames)
    assert frames == before


def test_ingress_rule_sequence_is_visible_and_ordered():
    # The coordinator exposes its ordered rule sequence so later normalizations
    # can be added without hiding logic in orchestration. E2 ordinary
    # structural admission (Phase-E slice E5 wiring) runs first; the
    # legend-blocks authoring delegate still runs before generic metadata
    # substrate admission.
    names = [rule.name for rule in INGRESS_RULES]
    assert names[0] == "ordinary_structural_admission"
    assert names.index("legend_blocks_shape") < names.index("metadata_substrate")
    assert len(names) == len(set(names))
