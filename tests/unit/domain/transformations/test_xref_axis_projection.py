"""Focused tests for flat one-level XRef axis-label projection (Slice 2).

These exercise the outbound/inbound transformations composed around unchanged
``contract_xref`` / ``expand_xref``: substitution correctness, the pure Frames
roundtrip under both order policies, failure diagnostics, ownership and
build-then-publish atomicity, and ``_meta`` pass-through.
"""
from __future__ import annotations

import copy

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.xref_axis_mapping import (
    AxisMappingError,
    AxisOrderPolicy,
)
from spreadsheet_handling.domain.transformations.xref_axis_projection import (
    project_axis_labels,
    restore_axis_keys,
)
from spreadsheet_handling.domain.transformations.xref_crosstable import (
    contract_xref,
    expand_xref,
)

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")


def _source_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"char_id": "CHAR-0002", "char_name": "Galli", "rank": 2},
            {"char_id": "CHAR-0007", "char_name": "Trixi", "rank": 1},
        ]
    )


def _canonical_relation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"story_id": "S1", "column_key": "CHAR-0002", "value": "x"},
            {"story_id": "S1", "column_key": "CHAR-0007", "value": "y"},
            {"story_id": "S2", "column_key": "CHAR-0002", "value": "z"},
        ]
    )


def _frames() -> dict[str, object]:
    return {"chars": _source_frame(), "rel": _canonical_relation()}


# --------------------------------------------------------------------------- #
# Substitution correctness
# --------------------------------------------------------------------------- #


def test_outbound_replaces_canonical_keys_with_flat_labels() -> None:
    frames = _frames()
    out = project_axis_labels(
        frames,
        relation="rel",
        output="rel_lbl",
        source_frame="chars",
        key_column="char_id",
        label_column="char_name",
    )
    assert out["rel_lbl"]["column_key"].tolist() == ["Galli", "Trixi", "Galli"]
    # Other columns and row order are preserved.
    assert out["rel_lbl"]["story_id"].tolist() == ["S1", "S1", "S2"]
    assert out["rel_lbl"]["value"].tolist() == ["x", "y", "z"]


def test_inbound_replaces_flat_labels_with_canonical_keys() -> None:
    frames = {
        "chars": _source_frame(),
        "rel": pd.DataFrame(
            [
                {"story_id": "S1", "column_key": "Galli", "value": "x"},
                {"story_id": "S2", "column_key": "Trixi", "value": "y"},
            ]
        ),
    }
    out = restore_axis_keys(
        frames,
        relation="rel",
        output="rel_key",
        source_frame="chars",
        key_column="char_id",
        label_column="char_name",
    )
    assert out["rel_key"]["column_key"].tolist() == ["CHAR-0002", "CHAR-0007"]


def test_custom_axis_identity_column_is_honoured() -> None:
    frames = {
        "chars": _source_frame(),
        "rel": pd.DataFrame(
            [{"story_id": "S1", "axis": "CHAR-0002", "value": "x"}]
        ),
    }
    out = project_axis_labels(
        frames,
        relation="rel",
        output="rel_lbl",
        source_frame="chars",
        key_column="char_id",
        label_column="char_name",
        column_key="axis",
    )
    assert out["rel_lbl"]["axis"].tolist() == ["Galli"]


# --------------------------------------------------------------------------- #
# Pure Frames roundtrip through unchanged XRef
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "order_policy, order_columns",
    [
        ("source_row", ()),
        ("columns", ("rank",)),
        (AxisOrderPolicy.SOURCE_ROW, ()),
    ],
)
def test_pure_frames_roundtrip_is_identity(order_policy, order_columns) -> None:
    frames = _frames()

    labelled = project_axis_labels(
        frames,
        relation="rel",
        output="rel_lbl",
        source_frame="chars",
        key_column="char_id",
        label_column="char_name",
        order_policy=order_policy,
        order_columns=order_columns,
    )
    matrix = contract_xref(
        labelled, relation="rel_lbl", output="matrix", row_keys="story_id"
    )
    # Readable header labels reach the matrix.
    assert set(matrix["matrix"].columns) == {"story_id", "Galli", "Trixi"}

    expanded = expand_xref(
        matrix, matrix="matrix", output="rel_lbl2", row_keys="story_id", drop_empty=True
    )
    restored = restore_axis_keys(
        expanded,
        relation="rel_lbl2",
        output="rel_back",
        source_frame="chars",
        key_column="char_id",
        label_column="char_name",
        order_policy=order_policy,
        order_columns=order_columns,
    )

    # The canonical axis vocabulary survives the roundtrip exactly, regardless
    # of ordering policy (substitution does not consume member order).
    got = restored["rel_back"][["story_id", "column_key", "value"]]
    got = got.sort_values(["story_id", "column_key"]).reset_index(drop=True)
    want = _canonical_relation().sort_values(["story_id", "column_key"]).reset_index(
        drop=True
    )
    pd.testing.assert_frame_equal(got, want, check_dtype=False)


def test_roundtrip_result_is_order_policy_independent() -> None:
    frames = _frames()

    def _restored(order_policy, order_columns):
        labelled = project_axis_labels(
            frames,
            relation="rel",
            output="rel_lbl",
            source_frame="chars",
            key_column="char_id",
            label_column="char_name",
            order_policy=order_policy,
            order_columns=order_columns,
        )
        return labelled["rel_lbl"]["column_key"].tolist()

    assert _restored("source_row", ()) == _restored("columns", ("rank",))


# --------------------------------------------------------------------------- #
# Failure diagnostics (explicit correctness obligations)
# --------------------------------------------------------------------------- #


def test_outbound_unknown_canonical_key_fails() -> None:
    frames = {
        "chars": _source_frame(),
        "rel": pd.DataFrame(
            [{"story_id": "S1", "column_key": "CHAR-9999", "value": "x"}]
        ),
    }
    with pytest.raises(AxisMappingError):
        project_axis_labels(
            frames,
            relation="rel",
            output="out",
            source_frame="chars",
            key_column="char_id",
            label_column="char_name",
        )


def test_inbound_unknown_visible_label_fails() -> None:
    frames = {
        "chars": _source_frame(),
        "rel": pd.DataFrame(
            [{"story_id": "S1", "column_key": "Nobody", "value": "x"}]
        ),
    }
    with pytest.raises(AxisMappingError):
        restore_axis_keys(
            frames,
            relation="rel",
            output="out",
            source_frame="chars",
            key_column="char_id",
            label_column="char_name",
        )


def test_missing_source_frame_fails() -> None:
    frames = {"rel": _canonical_relation()}
    with pytest.raises(AxisMappingError):
        project_axis_labels(
            frames,
            relation="rel",
            output="out",
            source_frame="chars",
            key_column="char_id",
            label_column="char_name",
        )


def test_missing_relation_frame_fails() -> None:
    frames = {"chars": _source_frame()}
    with pytest.raises(AxisMappingError):
        project_axis_labels(
            frames,
            relation="rel",
            output="out",
            source_frame="chars",
            key_column="char_id",
            label_column="char_name",
        )


def test_missing_axis_column_fails() -> None:
    frames = {
        "chars": _source_frame(),
        "rel": pd.DataFrame([{"story_id": "S1", "value": "x"}]),
    }
    with pytest.raises(AxisMappingError):
        project_axis_labels(
            frames,
            relation="rel",
            output="out",
            source_frame="chars",
            key_column="char_id",
            label_column="char_name",
        )


def test_duplicate_source_labels_fail_bijection() -> None:
    frames = {
        "chars": pd.DataFrame(
            [
                {"char_id": "CHAR-0002", "char_name": "Galli"},
                {"char_id": "CHAR-0007", "char_name": "Galli"},
            ]
        ),
        "rel": _canonical_relation(),
    }
    with pytest.raises(AxisMappingError):
        project_axis_labels(
            frames,
            relation="rel",
            output="out",
            source_frame="chars",
            key_column="char_id",
            label_column="char_name",
        )


def test_invalid_order_policy_string_fails() -> None:
    frames = _frames()
    with pytest.raises(AxisMappingError):
        project_axis_labels(
            frames,
            relation="rel",
            output="out",
            source_frame="chars",
            key_column="char_id",
            label_column="char_name",
            order_policy="nonsense",
        )


# --------------------------------------------------------------------------- #
# Ownership, atomicity, and _meta pass-through
# --------------------------------------------------------------------------- #


def test_inputs_are_not_mutated() -> None:
    frames = _frames()
    snapshot = copy.deepcopy(frames)
    project_axis_labels(
        frames,
        relation="rel",
        output="rel_lbl",
        source_frame="chars",
        key_column="char_id",
        label_column="char_name",
    )
    assert frames["rel"].equals(snapshot["rel"])
    assert frames["chars"].equals(snapshot["chars"])
    assert set(frames) == set(snapshot)


def test_failure_publishes_no_output_frame() -> None:
    frames = {
        "chars": _source_frame(),
        "rel": pd.DataFrame(
            [{"story_id": "S1", "column_key": "CHAR-9999", "value": "x"}]
        ),
    }
    before = set(frames)
    with pytest.raises(AxisMappingError):
        project_axis_labels(
            frames,
            relation="rel",
            output="out",
            source_frame="chars",
            key_column="char_id",
            label_column="char_name",
        )
    assert set(frames) == before
    assert "out" not in frames


def test_meta_is_passed_through_untouched_by_default() -> None:
    frames = _frames()
    frames["_meta"] = {"version": "9.9", "xref_crosstable": {"cfg": {"row_keys": ["story_id"]}}}
    meta_snapshot = copy.deepcopy(frames["_meta"])
    out = project_axis_labels(
        frames,
        relation="rel",
        output="rel_lbl",
        source_frame="chars",
        key_column="char_id",
        label_column="char_name",
    )
    # No new root written; the meta object is carried through unchanged.
    assert out["_meta"] == meta_snapshot
    assert frames["_meta"] == meta_snapshot


def test_drop_source_marks_relation_without_mutating_input_meta() -> None:
    frames = _frames()
    frames["_meta"] = {"version": "9.9"}
    out = project_axis_labels(
        frames,
        relation="rel",
        output="rel_lbl",
        source_frame="chars",
        key_column="char_id",
        label_column="char_name",
        drop_source=True,
    )
    assert out["_meta"]["pipeline_cleanup"]["drop_frames"] == ["rel"]
    # Input meta stays clean (build-then-publish; mark copies _meta).
    assert "pipeline_cleanup" not in frames["_meta"]


def test_drop_source_requires_distinct_output() -> None:
    frames = _frames()
    with pytest.raises(AxisMappingError):
        project_axis_labels(
            frames,
            relation="rel",
            output="rel",
            source_frame="chars",
            key_column="char_id",
            label_column="char_name",
            drop_source=True,
        )
