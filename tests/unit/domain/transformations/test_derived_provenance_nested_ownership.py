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
def test_enrich_lookup_provenance_write_invalidates_stale_output_on_decoupled_rebind(
    join_args: dict,
    expected: dict,
) -> None:
    """Decoupled rebind (``source != output``) discards stale prior provenance.

    ``result`` here is not this call's own ``source``, so the physical
    content ``enrich_lookup`` just published there has no provable
    relationship to whatever ``result`` held before -- a foreign FK sibling
    (``fk_entries``) or Lookup's own prior ``enrich_lookup`` record. Per the
    accepted deletion-authority design (Section K), both are invalidated
    unconditionally as part of this write, before the fresh record (if any)
    is established. This inverts the pre-Slice-3 characterization, which
    asserted the foreign entry survived untouched.
    """
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
    assert "helper_columns" not in out_sheet
    assert out_sheet["enrich_lookup"] == expected


# ---------------------------------------------------------------------------
# Slice 3: decoupled-rebind write-time invalidation (accepted deletion-
# authority design, Section K). FIND-D1/Repro 4, FIND-D9/Repro 5, the
# same-owner stale-record variant, the same-source over-invalidation guard,
# and the brand-new-output no-op are each proven directly against a real
# FK-materialized sibling, not only against a hand-built fixture.
# ---------------------------------------------------------------------------


def _fk_enriched_frames() -> dict:
    """``A`` truthfully carries FK's own materialized ``_B_name`` helper."""
    return enrich_helpers(_fk_frames(), _FK_DEFAULTS)


def test_enrich_lookup_fields_bearing_decoupled_rebind_invalidates_stale_fk_provenance() -> None:
    """FIND-D1 / Repro 4: a fields-bearing decoupled rebind drops FK's stale record.

    ``A`` already carries truthful FK helper provenance for ``_B_name`` from a
    prior ``add_fk_helpers`` call. An ordinary ``enrich_lookup(source="C",
    output="A", ...)`` call -- ``source != output`` -- physically replaces
    ``A`` with content derived from ``C``. FK's stale record must not survive
    that rebind, and a subsequent cleanup pass must not delete the
    replacement column on the strength of it.
    """
    fk_frames = _fk_enriched_frames()
    assert fk_frames["_meta"]["derived"]["sheets"]["A"]["helper_columns"]

    frames = dict(fk_frames)
    frames["C"] = pd.DataFrame({"id": [1, 2], "note": ["x", "y"]})

    out = enrich_lookup(
        frames,
        source="C",
        lookup="B",
        output="A",
        on="id",
        helpers={"fields": ["name"]},
    )

    out_sheet = out["_meta"]["derived"]["sheets"]["A"]
    assert "helper_columns" not in out_sheet
    assert out_sheet["enrich_lookup"] == {
        "lookup": "B",
        "on": ["id"],
        "helper_columns": ["name"],
    }
    assert "_B_name" not in out["A"].columns
    assert list(out["A"]["name"]) == ["alpha", "beta"]

    # A later cleanup does not delete the replacement column due to stale FK
    # provenance -- direct proof this slice's own contract holds; full
    # removal of the durable-policy fallback is Slices 4/5's job, not this
    # one's, so this assertion does not depend on that later change.
    cleaned = drop_helpers(out)
    assert "name" in cleaned["A"].columns


def test_enrich_lookup_helpers_none_decoupled_rebind_invalidates_stale_fk_provenance() -> None:
    """FIND-D9 / Repro 5: a ``helpers=None`` decoupled rebind still invalidates.

    Identical setup to the fields-bearing case above, except this call
    requests no helper projection at all. The physical rebind still occurs
    (``out[output] = enriched``), so FK's stale record must still be removed
    even though this call itself has no fresh provenance to establish.
    """
    fk_frames = _fk_enriched_frames()

    frames = dict(fk_frames)
    frames["C"] = pd.DataFrame({"id": [1, 2], "note": ["x", "y"]})

    out = enrich_lookup(
        frames,
        source="C",
        lookup="B",
        output="A",
        on="id",
        helpers=None,
    )

    assert "A" not in out["_meta"]["derived"]["sheets"]
    assert "_B_name" not in out["A"].columns


def test_enrich_lookup_decoupled_rebind_invalidates_stale_own_lookup_record() -> None:
    """Same-owner stale-record variant (Review 002 Section 5).

    A first ``enrich_lookup`` call establishes Lookup's own provenance at
    ``B``. A later, decoupled ``enrich_lookup(source="C", output="B",
    helpers=None)`` call has no fresh record to re-establish it with, so the
    prior *own* record must be removed too, not only a foreign FK sibling.
    """
    frames = _lookup_frames()
    first = enrich_lookup(
        frames,
        source="src",
        lookup="lookup",
        output="B",
        on="id",
        helpers={"fields": ["title"]},
    )
    assert first["_meta"]["derived"]["sheets"]["B"]["enrich_lookup"]["helper_columns"] == [
        "title"
    ]

    frames2 = dict(first)
    frames2["C"] = pd.DataFrame({"id": [1, 2], "note": ["x", "y"]})

    out = enrich_lookup(
        frames2,
        source="C",
        lookup="lookup",
        output="B",
        on="id",
        helpers=None,
    )

    assert "B" not in out["_meta"]["derived"]["sheets"]


def test_enrich_lookup_same_source_preserves_sibling_fk_provenance_helpers_present() -> None:
    """Over-invalidation guard: ``output == source`` never discards siblings.

    Self-extension (``source == output``) must remain a true no-op for prior
    sibling provenance and physical FK-owned values, whether or not this
    call itself carries fresh helper fields.
    """
    fk_frames = _fk_enriched_frames()
    fk_entry = fk_frames["_meta"]["derived"]["sheets"]["A"]["helper_columns"]
    original_b_name = list(fk_frames["A"]["_B_name"])

    frames = dict(fk_frames)
    frames["extra_lookup"] = pd.DataFrame({"id": [10, 20], "title": ["t1", "t2"]})

    out = enrich_lookup(
        frames,
        source="A",
        lookup="extra_lookup",
        output="A",
        on="id",
        helpers={"fields": ["title"]},
    )

    out_sheet = out["_meta"]["derived"]["sheets"]["A"]
    assert out_sheet["helper_columns"] is fk_entry
    assert out_sheet["enrich_lookup"] == {
        "lookup": "extra_lookup",
        "on": ["id"],
        "helper_columns": ["title"],
    }
    assert list(out["A"]["_B_name"]) == original_b_name
    assert list(out["A"]["title"]) == ["t1", "t2"]


def test_enrich_lookup_same_source_preserves_sibling_fk_provenance_helpers_none() -> None:
    fk_frames = _fk_enriched_frames()
    fk_entry = fk_frames["_meta"]["derived"]["sheets"]["A"]["helper_columns"]
    original_b_name = list(fk_frames["A"]["_B_name"])

    frames = dict(fk_frames)
    frames["extra_lookup"] = pd.DataFrame({"id": [10, 20], "title": ["t1", "t2"]})

    out = enrich_lookup(
        frames,
        source="A",
        lookup="extra_lookup",
        output="A",
        on="id",
        helpers=None,
    )

    out_sheet = out["_meta"]["derived"]["sheets"]["A"]
    assert out_sheet["helper_columns"] is fk_entry
    assert "enrich_lookup" not in out_sheet
    assert list(out["A"]["_B_name"]) == original_b_name


def test_enrich_lookup_brand_new_output_decoupled_rebind_is_a_no_op() -> None:
    """Brand-new distinct output: behavior is unchanged from today.

    ``helpers=None`` into a brand-new output must not manufacture a `_meta`
    tree merely to represent an invalidation that has nothing to discard.
    """
    frames = _lookup_frames()

    out_with_fields = enrich_lookup(
        frames,
        source="src",
        lookup="lookup",
        output="brand_new",
        on="id",
        helpers={"fields": ["title"]},
    )
    assert out_with_fields["_meta"]["derived"]["sheets"]["brand_new"]["enrich_lookup"][
        "helper_columns"
    ] == ["title"]

    out_no_fields = enrich_lookup(
        frames,
        source="src",
        lookup="lookup",
        output="brand_new_2",
        on="id",
        helpers=None,
    )
    assert "_meta" not in out_no_fields


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


def test_fk_drop_delegates_lookup_provenance_reconciliation_to_lookup_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FK cleanup contains no direct Lookup key-shape interpretation.

    ``existing_lookup_helper`` is untouched by FK's own column removal and
    would be *retained* by the real Lookup reconciliation (its declared
    helper column is still present). Stubbing the Lookup-owned boundary to
    unconditionally say "not truthful" and observing the record disappear
    anyway proves FK-drop defers the decision entirely to that boundary
    rather than computing its own presence/overlap answer.
    """
    import spreadsheet_handling.domain.transformations.fk_helpers.provenance as fk_provenance

    frames = enrich_helpers(_fk_frames(), _FK_DEFAULTS)
    frames["A"]["existing_lookup_helper"] = ["x", "y"]
    frames["_meta"]["derived"]["sheets"]["A"]["enrich_lookup"] = {
        "lookup": "B",
        "on": ["id_(B)"],
        "helper_columns": ["existing_lookup_helper"],
    }

    monkeypatch.setattr(
        fk_provenance, "reconcile_enrich_lookup_provenance", lambda *a, **k: False
    )

    out = drop_helpers(frames)

    assert "existing_lookup_helper" in out["A"].columns
    assert "enrich_lookup" not in out["_meta"].get("derived", {}).get("sheets", {}).get(
        "A", {}
    )


def test_fk_drop_malformed_enrich_lookup_helper_columns_fails_clearly() -> None:
    """Malformed Lookup provenance at the FK-drop seam fails before publication.

    FIND-001: previously ``.get("helper_columns") or []`` silently
    misinterpreted (or opaquely crashed on) a malformed shape. The
    Lookup-owned boundary now raises a clear, path-specific ``ValueError``
    reachable through ``drop_helpers``, and no partial output/meta is
    published.
    """
    frames = enrich_helpers(_fk_frames(), _FK_DEFAULTS)
    frames["_meta"]["derived"]["sheets"]["A"]["enrich_lookup"] = {
        "lookup": "B",
        "on": ["id_(B)"],
        "helper_columns": "not-a-list",
    }

    with pytest.raises(ValueError) as excinfo:
        drop_helpers(frames)

    message = str(excinfo.value)
    assert "_meta.derived.sheets['A'].enrich_lookup.helper_columns" in message
    assert "must be a list" in message


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
