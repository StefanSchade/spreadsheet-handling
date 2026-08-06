"""Caller-ownership characterization for transient derived provenance."""
from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest

from spreadsheet_handling.domain.fk_relations import infer_fk_relations
from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup
from spreadsheet_handling.domain.transformations.fk_helpers import (
    drop_helpers,
    enrich_helpers,
)


pytestmark = pytest.mark.ftr("FTR-DERIVED-PROVENANCE-NESTED-OWNERSHIP-P4A")

_FK_DEFAULTS = {"id_field": "id", "label_field": "name", "helper_prefix": "_"}


def _fk_frames() -> dict:
    return infer_fk_relations(
        {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]}),
        }
    )


def _lookup_frames() -> dict:
    return {
        "src": pd.DataFrame({"id": [1, 2], "story_id": [1, 2]}),
        "lookup": pd.DataFrame(
            {
                "id": [1, 2],
                "title": ["First", "Second"],
                "code": ["one", "two"],
            }
        ),
    }


def _snapshot_data_frames(frames: dict) -> dict[str, pd.DataFrame]:
    return {
        name: value.copy(deep=True)
        for name, value in frames.items()
        if isinstance(value, pd.DataFrame)
    }


def _assert_input_frames_unchanged(
    frames: dict,
    mapping_snapshot: dict,
    data_frame_snapshots: dict[str, pd.DataFrame],
) -> None:
    assert set(frames) == set(mapping_snapshot)
    for name, original_value in mapping_snapshot.items():
        assert frames[name] is original_value
    for name, snapshot in data_frame_snapshots.items():
        pd.testing.assert_frame_equal(frames[name], snapshot)


def test_fk_provenance_write_copies_only_changed_path_and_preserves_siblings() -> None:
    frames = _fk_frames()
    keep = {"token": "top-level sibling"}
    unrelated_derived = {"token": "derived sibling"}
    enrich_record = {
        "lookup": "B",
        "on": ["id_(B)"],
        "helper_columns": ["existing_lookup_helper"],
    }
    untouched_sheet = {"other_producer": {"token": "sheet sibling"}}
    frames["_meta"]["keep"] = keep
    frames["_meta"]["derived"] = {
        "other_namespace": unrelated_derived,
        "sheets": {
            "A": {"enrich_lookup": enrich_record},
            "B": untouched_sheet,
            "Gone": {
                "helper_columns": [
                    {
                        "column": "_old",
                        "fk_column": "id_(old)",
                        "target": "old",
                        "target_key": "id",
                        "value_field": "name",
                    }
                ]
            },
        },
    }

    input_mapping_snapshot = dict(frames)
    data_frame_snapshots = _snapshot_data_frames(frames)
    input_meta = frames["_meta"]
    input_derived = input_meta["derived"]
    input_sheets = input_derived["sheets"]
    input_sheet = input_sheets["A"]
    meta_snapshot = deepcopy(input_meta)
    derived_snapshot = deepcopy(input_derived)
    sheets_snapshot = deepcopy(input_sheets)
    sheet_snapshot = deepcopy(input_sheet)

    out = enrich_helpers(frames, _FK_DEFAULTS)

    _assert_input_frames_unchanged(
        frames, input_mapping_snapshot, data_frame_snapshots
    )
    assert input_meta == meta_snapshot
    assert input_derived == derived_snapshot
    assert input_sheets == sheets_snapshot
    assert input_sheet == sheet_snapshot

    out_meta = out["_meta"]
    out_derived = out_meta["derived"]
    out_sheets = out_derived["sheets"]
    out_sheet = out_sheets["A"]
    assert out_meta is not input_meta
    assert out_derived is not input_derived
    assert out_sheets is not input_sheets
    assert out_sheet is not input_sheet
    assert out_meta["keep"] is keep
    assert out_derived["other_namespace"] is unrelated_derived
    assert out_sheets["B"] is untouched_sheet
    assert out_sheet["enrich_lookup"] is enrich_record
    assert "Gone" not in out_sheets
    assert out_sheet["helper_columns"] == [
        {
            "column": "_B_name",
            "fk_column": "id_(B)",
            "target": "B",
            "target_key": "id",
            "value_field": "name",
        }
    ]


def test_fk_cleanup_preserves_input_and_presence_checked_siblings_on_repeat() -> None:
    frames = enrich_helpers(_fk_frames(), _FK_DEFAULTS)
    frames["A"]["existing_lookup_helper"] = ["x", "y"]
    enrich_record = {
        "lookup": "B",
        "on": ["id_(B)"],
        "helper_columns": ["existing_lookup_helper"],
    }
    frames["_meta"]["derived"]["sheets"]["A"]["enrich_lookup"] = enrich_record
    untouched_sheet = {"other_producer": {"token": "untouched"}}
    frames["_meta"]["derived"]["sheets"]["B"] = untouched_sheet

    input_mapping_snapshot = dict(frames)
    data_frame_snapshots = _snapshot_data_frames(frames)
    input_meta = frames["_meta"]
    input_derived = input_meta["derived"]
    input_sheets = input_derived["sheets"]
    input_sheet = input_sheets["A"]
    meta_snapshot = deepcopy(input_meta)
    derived_snapshot = deepcopy(input_derived)
    sheets_snapshot = deepcopy(input_sheets)
    sheet_snapshot = deepcopy(input_sheet)

    out = drop_helpers(frames)

    _assert_input_frames_unchanged(
        frames, input_mapping_snapshot, data_frame_snapshots
    )
    assert input_meta == meta_snapshot
    assert input_derived == derived_snapshot
    assert input_sheets == sheets_snapshot
    assert input_sheet == sheet_snapshot

    out_meta = out["_meta"]
    out_derived = out_meta["derived"]
    out_sheets = out_derived["sheets"]
    out_sheet = out_sheets["A"]
    assert out_meta is not input_meta
    assert out_derived is not input_derived
    assert out_sheets is not input_sheets
    assert out_sheet is not input_sheet
    assert "helper_columns" not in out_sheet
    assert out_sheet["enrich_lookup"] is enrich_record
    assert out_sheets["B"] is untouched_sheet
    assert "_B_name" not in out["A"].columns
    assert "existing_lookup_helper" in out["A"].columns

    repeated = drop_helpers(out)
    assert repeated["_meta"]["derived"] is out_derived
    assert repeated["_meta"]["derived"]["sheets"] is out_sheets
    assert repeated["_meta"]["derived"]["sheets"]["A"] is out_sheet
    assert repeated["_meta"]["derived"]["sheets"]["A"]["enrich_lookup"] == enrich_record


def test_fk_cleanup_conditionally_removes_enrich_and_prunes_empty_containers() -> None:
    frames = enrich_helpers(_fk_frames(), _FK_DEFAULTS)
    frames["_meta"]["derived"]["sheets"]["A"]["enrich_lookup"] = {
        "lookup": "B",
        "on": ["id_(B)"],
        "helper_columns": ["_B_name"],
    }
    input_meta = frames["_meta"]
    input_derived = input_meta["derived"]
    input_sheets = input_derived["sheets"]
    input_sheet = input_sheets["A"]
    meta_snapshot = deepcopy(input_meta)
    derived_snapshot = deepcopy(input_derived)
    sheets_snapshot = deepcopy(input_sheets)
    sheet_snapshot = deepcopy(input_sheet)

    out = drop_helpers(frames)

    assert input_meta == meta_snapshot
    assert input_derived == derived_snapshot
    assert input_sheets == sheets_snapshot
    assert input_sheet == sheet_snapshot
    assert "derived" not in out["_meta"]
    assert "_B_name" not in out["A"].columns

    repeated = drop_helpers(out)
    assert "derived" not in repeated["_meta"]
    assert list(repeated["A"].columns) == list(out["A"].columns)


@pytest.mark.parametrize("container_case", ["meta", "derived", "sheets", "sheet"])
def test_enrich_lookup_creates_only_missing_provenance_containers(
    container_case: str,
) -> None:
    frames = _lookup_frames()
    if container_case == "derived":
        frames["_meta"] = {"keep": {"token": "top"}}
    elif container_case == "sheets":
        frames["_meta"] = {
            "keep": {"token": "top"},
            "derived": {"other_namespace": {"token": "derived"}},
        }
    elif container_case == "sheet":
        frames["_meta"] = {
            "keep": {"token": "top"},
            "derived": {
                "other_namespace": {"token": "derived"},
                "sheets": {"untouched": {"token": "sheet"}},
            },
        }
    input_snapshot = deepcopy(frames.get("_meta"))

    out = enrich_lookup(
        frames,
        source="src",
        lookup="lookup",
        output="result",
        on="id",
        helpers={"fields": ["title"]},
    )

    assert frames.get("_meta") == input_snapshot
    assert out["_meta"]["derived"]["sheets"]["result"]["enrich_lookup"] == {
        "lookup": "lookup",
        "on": ["id"],
        "helper_columns": ["title"],
    }


@pytest.mark.parametrize(
    ("join_args", "expected"),
    [
        (
            {"on": "id"},
            {"lookup": "lookup", "on": ["id"], "helper_columns": ["title"]},
        ),
        (
            {"source_key": "story_id", "lookup_key": "id"},
            {
                "lookup": "lookup",
                "source_key": "story_id",
                "lookup_key": "id",
                "helper_columns": ["title"],
            },
        ),
        (
            {"source_key": "id", "lookup_key": "id"},
            {
                "lookup": "lookup",
                "source_key": "id",
                "lookup_key": "id",
                "helper_columns": ["title"],
            },
        ),
    ],
)
def test_enrich_lookup_provenance_write_preserves_nested_caller_ownership(
    join_args: dict,
    expected: dict,
) -> None:
    frames = _lookup_frames()
    keep = {"token": "top-level sibling"}
    unrelated_derived = {"token": "derived sibling"}
    fk_entries = [{"column": "_fk_helper"}]
    untouched_sheet = {"other_producer": {"token": "sheet sibling"}}
    frames["_meta"] = {
        "keep": keep,
        "derived": {
            "other_namespace": unrelated_derived,
            "sheets": {
                "result": {
                    "helper_columns": fk_entries,
                    "enrich_lookup": {
                        "lookup": "old",
                        "on": ["id"],
                        "helper_columns": ["old_helper"],
                    },
                },
                "untouched": untouched_sheet,
            },
        },
    }

    input_mapping_snapshot = dict(frames)
    data_frame_snapshots = _snapshot_data_frames(frames)
    input_meta = frames["_meta"]
    input_derived = input_meta["derived"]
    input_sheets = input_derived["sheets"]
    input_sheet = input_sheets["result"]
    meta_snapshot = deepcopy(input_meta)
    derived_snapshot = deepcopy(input_derived)
    sheets_snapshot = deepcopy(input_sheets)
    sheet_snapshot = deepcopy(input_sheet)

    out = enrich_lookup(
        frames,
        source="src",
        lookup="lookup",
        output="result",
        helpers={"fields": ["title"]},
        **join_args,
    )

    _assert_input_frames_unchanged(
        frames, input_mapping_snapshot, data_frame_snapshots
    )
    assert input_meta == meta_snapshot
    assert input_derived == derived_snapshot
    assert input_sheets == sheets_snapshot
    assert input_sheet == sheet_snapshot

    out_meta = out["_meta"]
    out_derived = out_meta["derived"]
    out_sheets = out_derived["sheets"]
    out_sheet = out_sheets["result"]
    assert out_meta is not input_meta
    assert out_derived is not input_derived
    assert out_sheets is not input_sheets
    assert out_sheet is not input_sheet
    assert out_meta["keep"] is keep
    assert out_derived["other_namespace"] is unrelated_derived
    assert out_sheets["untouched"] is untouched_sheet
    assert out_sheet["helper_columns"] is fk_entries
    assert out_sheet["enrich_lookup"] == expected


def test_enrich_lookup_repetition_matrix_preserves_current_stale_behavior() -> None:
    frames = _lookup_frames()
    first = enrich_lookup(
        frames,
        source="src",
        lookup="lookup",
        output="old_output",
        on="id",
        helpers={"fields": ["title"]},
    )

    identical = enrich_lookup(
        first,
        source="src",
        lookup="lookup",
        output="old_output",
        on="id",
        helpers={"fields": ["title"]},
    )
    assert identical["_meta"]["derived"]["sheets"]["old_output"][
        "enrich_lookup"
    ] == {
        "lookup": "lookup",
        "on": ["id"],
        "helper_columns": ["title"],
    }

    changed_helpers = enrich_lookup(
        first,
        source="src",
        lookup="lookup",
        output="old_output",
        on="id",
        helpers={"fields": ["code"]},
    )
    assert changed_helpers["_meta"]["derived"]["sheets"]["old_output"][
        "enrich_lookup"
    ]["helper_columns"] == ["code"]

    source_replaced = enrich_lookup(
        frames,
        source="src",
        lookup="lookup",
        output="src",
        on="id",
        helpers={"fields": ["title"]},
    )
    assert "title" in source_replaced["src"].columns
    assert "title" not in frames["src"].columns
    assert source_replaced["_meta"]["derived"]["sheets"]["src"][
        "enrich_lookup"
    ]["helper_columns"] == ["title"]

    renamed = enrich_lookup(
        first,
        source="src",
        lookup="lookup",
        output="new_output",
        on="id",
        helpers={"fields": ["code"]},
    )
    assert "old_output" in renamed
    assert "new_output" in renamed
    assert set(renamed["_meta"]["derived"]["sheets"]) == {
        "old_output",
        "new_output",
    }

    without_old_output = dict(first)
    del without_old_output["old_output"]
    after_caller_removal = enrich_lookup(
        without_old_output,
        source="src",
        lookup="lookup",
        output="new_output",
        on="id",
        helpers={"fields": ["code"]},
    )
    assert "old_output" not in after_caller_removal
    # Slice 1 deliberately preserves the producer's existing no-stale-cleanup
    # behavior: caller-removed outputs do not authorize a wider provenance scan.
    assert set(after_caller_removal["_meta"]["derived"]["sheets"]) == {
        "old_output",
        "new_output",
    }


@pytest.mark.parametrize("container_case", ["meta", "derived", "sheets"])
def test_fk_write_and_drop_handle_absent_containers_without_spurious_empty_meta(
    container_case: str,
) -> None:
    frames = _fk_frames()
    if container_case == "derived":
        frames["_meta"]["keep"] = {"token": "top"}
    elif container_case == "sheets":
        frames["_meta"]["derived"] = {"other_namespace": {"token": "derived"}}
    input_meta_snapshot = deepcopy(frames["_meta"])

    enriched = enrich_helpers(frames, _FK_DEFAULTS)

    assert frames["_meta"] == input_meta_snapshot
    assert enriched["_meta"]["derived"]["sheets"]["A"]["helper_columns"]

    without_provenance = _fk_frames()
    without_provenance_meta_snapshot = deepcopy(without_provenance["_meta"])
    cleaned = drop_helpers(without_provenance)
    assert without_provenance["_meta"] == without_provenance_meta_snapshot
    assert "derived" not in cleaned["_meta"]
