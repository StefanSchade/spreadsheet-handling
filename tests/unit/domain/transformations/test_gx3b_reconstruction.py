"""GX-3b reverse reconstruction: an exact table becomes a GroupedMatrix.

GX-3b of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. ``reconstruct_grouped_matrix`` turns a
parsed :class:`ExactTable` into a validated :class:`GroupedMatrix` under exactly
one live axis mapping, identifying row keys by leaf label, normalising
merge-repeat blanks, and rejecting unknown/duplicate/incomplete tuples, wrong
depth, and stale mappings. Publication is atomic.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.exact_table import ExactTable
from spreadsheet_handling.domain.transformations.grouped_xref import (
    GroupedMatrix,
    GroupedXrefError,
    contract_grouped_xref,
    grouped_matrix_to_exact_table,
    reconstruct_grouped_matrix,
)
from spreadsheet_handling.domain.transformations import grouped_xref
from spreadsheet_handling.domain.transformations.xref_axis_mapping import AxisMappingError

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")


def _source():
    keys = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")
    return keys, pd.DataFrame(
        {
            "key": list(keys),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitaet", "Festzins", "Guthaben"],
        }
    )


def _grouped_matrix(row_keys=("row_id",), label_columns=("grp", "leaf")):
    keys, source = _source()
    relation = pd.DataFrame(
        [
            {"row_id": rid, "column_key": k, "value": f"{rid}:{k}"}
            for rid in ("r1", "r2")
            for k in keys
        ]
    )
    out = contract_grouped_xref(
        {"rel": relation, "src": source},
        relation="rel",
        output="Matrix",
        row_keys=list(row_keys),
        source_frame="src",
        key_column="key",
        label_columns=list(label_columns),
    )
    return out["Matrix"], source


def _reconstruct(exact, source, **overrides):
    kwargs = dict(
        table="Matrix",
        output="mtx",
        row_keys=["row_id"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    kwargs.update(overrides)
    return reconstruct_grouped_matrix({"Matrix": exact, "src": source}, **kwargs)


def test_untouched_exact_roundtrip_reconstructs_identical_carrier():
    gm, source = _grouped_matrix()
    exact = grouped_matrix_to_exact_table(gm)
    out = _reconstruct(exact, source)
    assert isinstance(out["mtx"], GroupedMatrix)
    assert out["mtx"].header == gm.header
    pd.testing.assert_frame_equal(
        out["mtx"].frame.reset_index(drop=True), gm.frame.reset_index(drop=True)
    )


def test_factory_integration_returns_validated_grouped_matrix():
    gm, source = _grouped_matrix()
    out = _reconstruct(grouped_matrix_to_exact_table(gm), source)
    # constructed through grouped_matrix_from_canonical, not raw construction.
    assert type(out["mtx"]) is GroupedMatrix


def test_edited_data_values_are_preserved():
    gm, source = _grouped_matrix()
    exact = grouped_matrix_to_exact_table(gm)
    edited = list(list(r) for r in exact.data)
    edited[0][1] = "EDITED"
    exact2 = ExactTable(
        header_grid=exact.header_grid,
        data=tuple(tuple(r) for r in edited),
        header_rows=exact.header_rows,
        n_cols=exact.n_cols,
    )
    out = _reconstruct(exact2, source)
    assert out["mtx"].frame.iloc[0, 1] == "EDITED"


def test_dynamic_column_reorder_is_supported():
    gm, source = _grouped_matrix()
    exact = grouped_matrix_to_exact_table(gm)
    # swap the two credit dynamic columns (positions 1 and 2) in header + data.
    def swap(row):
        row = list(row)
        row[1], row[2] = row[2], row[1]
        return tuple(row)

    exact2 = ExactTable(
        header_grid=tuple(swap(r) for r in exact.header_grid),
        data=tuple(swap(r) for r in exact.data),
        header_rows=exact.header_rows,
        n_cols=exact.n_cols,
    )
    out = _reconstruct(exact2, source)
    cols = list(out["mtx"].frame.columns)
    assert cols[1] == "credit.fixed_rate_loan"
    assert cols[2] == "credit.annuity_loan"


def test_valid_dynamic_column_deletion_yields_smaller_matrix():
    gm, source = _grouped_matrix()
    exact = grouped_matrix_to_exact_table(gm)
    # drop the last dynamic column (deposit).
    def drop_last(row):
        return tuple(row[:-1])

    exact2 = ExactTable(
        header_grid=tuple(drop_last(r) for r in exact.header_grid),
        data=tuple(drop_last(r) for r in exact.data),
        header_rows=exact.header_rows,
        n_cols=exact.n_cols - 1,
    )
    out = _reconstruct(exact2, source)
    assert len(out["mtx"].header.columns) == 3
    assert "deposit.balance" not in out["mtx"].frame.columns


def test_multiple_row_keys_reconstruct_by_leaf_label():
    keys = ("a.x", "b.y")
    source = pd.DataFrame({"key": list(keys), "grp": ["A", "B"], "leaf": ["x", "y"]})
    exact = ExactTable(
        header_grid=(("", "", "A", "B"), ("r1", "r2", "x", "y")),
        data=(("p", "q", "1", "2"),),
        header_rows=2,
        n_cols=4,
    )
    out = reconstruct_grouped_matrix(
        {"Matrix": exact, "src": source},
        table="Matrix",
        output="mtx",
        row_keys=["r1", "r2"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    cols = list(out["mtx"].frame.columns)
    assert cols[:2] == ["r1", "r2"]
    assert cols[2:] == ["a.x", "b.y"]


def test_moved_row_key_is_supported_when_leaf_label_is_unique():
    keys = ("a.x", "b.y")
    source = pd.DataFrame({"key": list(keys), "grp": ["A", "B"], "leaf": ["x", "y"]})
    # row_id is the LAST physical column.
    exact = ExactTable(
        header_grid=(("A", "B", ""), ("x", "y", "row_id")),
        data=(("1", "2", "r1"),),
        header_rows=2,
        n_cols=3,
    )
    out = reconstruct_grouped_matrix(
        {"Matrix": exact, "src": source},
        table="Matrix",
        output="mtx",
        row_keys=["row_id"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    assert list(out["mtx"].frame.columns) == ["a.x", "b.y", "row_id"]


def test_literal_delimiter_component_is_not_split():
    keys = ("a.x", "b.y")
    source = pd.DataFrame(
        {"key": list(keys), "grp": ["G / H", "Einlage"], "leaf": ["x", "y"]}
    )
    exact = ExactTable(
        header_grid=(("", "G / H", "Einlage"), ("row_id", "x", "y")),
        data=(("r1", "1", "2"),),
        header_rows=2,
        n_cols=3,
    )
    out = reconstruct_grouped_matrix(
        {"Matrix": exact, "src": source},
        table="Matrix",
        output="mtx",
        row_keys=["row_id"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    assert list(out["mtx"].frame.columns) == ["row_id", "a.x", "b.y"]


def test_arity3_reconstructs():
    keys = ("a.x", "a.y", "b.z")
    source = pd.DataFrame(
        {"key": list(keys), "l1": ["A", "A", "B"], "l2": ["A1", "A1", "B1"], "l3": ["x", "y", "z"]}
    )
    exact = ExactTable(
        header_grid=(
            ("", "A", "A", "B"),
            ("", "A1", "A1", "B1"),
            ("row_id", "x", "y", "z"),
        ),
        data=(("r1", "1", "2", "3"),),
        header_rows=3,
        n_cols=4,
    )
    out = reconstruct_grouped_matrix(
        {"Matrix": exact, "src": source},
        table="Matrix",
        output="mtx",
        row_keys=["row_id"],
        source_frame="src",
        key_column="key",
        label_columns=["l1", "l2", "l3"],
    )
    assert list(out["mtx"].frame.columns) == ["row_id", "a.x", "a.y", "b.z"]


def test_raw_merge_repeat_blanks_are_normalised():
    keys = ("a.x", "a.y", "b.z")
    source = pd.DataFrame(
        {"key": list(keys), "grp": ["A", "A", "B"], "leaf": ["x", "y", "z"]}
    )
    # upper "A" appears once then a merge-repeat blank; row-key upper stays blank.
    exact = ExactTable(
        header_grid=(("", "A", "", "B"), ("row_id", "x", "y", "z")),
        data=(("r1", "1", "2", "3"),),
        header_rows=2,
        n_cols=4,
    )
    out = reconstruct_grouped_matrix(
        {"Matrix": exact, "src": source},
        table="Matrix",
        output="mtx",
        row_keys=["row_id"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    assert list(out["mtx"].frame.columns) == ["row_id", "a.x", "a.y", "b.z"]


def test_unknown_tuple_is_rejected():
    _keys, source = _source()
    exact = ExactTable(
        header_grid=(("", "Kredit"), ("row_id", "Unbekannt")),
        data=(("r1", "1"),),
        header_rows=2,
        n_cols=2,
    )
    with pytest.raises(AxisMappingError):
        _reconstruct(exact, source)


def test_duplicate_tuple_is_rejected():
    _keys, source = _source()
    exact = ExactTable(
        header_grid=(("", "Kredit", "Kredit"), ("row_id", "Annuitaet", "Annuitaet")),
        data=(("r1", "1", "2"),),
        header_rows=2,
        n_cols=3,
    )
    with pytest.raises(GroupedXrefError):
        _reconstruct(exact, source)


def test_incomplete_tuple_is_rejected():
    _keys, source = _source()
    # a dynamic column with a blank leaf component (no fill can complete it).
    exact = ExactTable(
        header_grid=(("", "Kredit"), ("row_id", "")),
        data=(("r1", "1"),),
        header_rows=2,
        n_cols=2,
    )
    with pytest.raises(GroupedXrefError):
        _reconstruct(exact, source)


def test_wrong_depth_is_rejected():
    _keys, source = _source()
    exact = grouped_matrix_to_exact_table(_grouped_matrix()[0])
    with pytest.raises(GroupedXrefError):
        _reconstruct(exact, source, label_columns=["grp"])  # depth 1 vs grid depth 2


def test_missing_row_key_is_rejected():
    gm, source = _grouped_matrix()
    exact = grouped_matrix_to_exact_table(gm)
    with pytest.raises(GroupedXrefError):
        _reconstruct(exact, source, row_keys=["absent"])


def test_duplicate_row_key_leaf_label_is_rejected():
    keys = ("a.x",)
    source = pd.DataFrame({"key": list(keys), "grp": ["A"], "leaf": ["x"]})
    exact = ExactTable(
        header_grid=(("", "", "A"), ("row_id", "row_id", "x")),
        data=(("p", "q", "1"),),
        header_rows=2,
        n_cols=3,
    )
    with pytest.raises(GroupedXrefError):
        reconstruct_grouped_matrix(
            {"Matrix": exact, "src": source},
            table="Matrix",
            output="mtx",
            row_keys=["row_id"],
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_non_blank_upper_above_row_key_is_rejected():
    _keys, source = _source()
    exact = ExactTable(
        header_grid=(("NOTBLANK", "Kredit"), ("row_id", "Annuitaet")),
        data=(("r1", "1"),),
        header_rows=2,
        n_cols=2,
    )
    with pytest.raises(GroupedXrefError):
        reconstruct_grouped_matrix(
            {"Matrix": exact, "src": source},
            table="Matrix",
            output="mtx",
            row_keys=["row_id"],
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_stale_mapping_is_rejected():
    gm, source = _grouped_matrix()
    exact = grouped_matrix_to_exact_table(gm)
    stale = source.copy()
    stale.loc[stale["leaf"] == "Annuitaet", "leaf"] = "Renamed"
    with pytest.raises(AxisMappingError):
        _reconstruct(exact, stale)


def test_non_exact_table_input_is_rejected():
    _keys, source = _source()
    with pytest.raises(GroupedXrefError):
        reconstruct_grouped_matrix(
            {"Matrix": pd.DataFrame({"x": [1]}), "src": source},
            table="Matrix",
            output="mtx",
            row_keys=["row_id"],
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_atomic_failure_leaves_frames_unchanged():
    _keys, source = _source()
    exact = ExactTable(
        header_grid=(("", "Kredit"), ("row_id", "Unbekannt")),
        data=(("r1", "1"),),
        header_rows=2,
        n_cols=2,
    )
    frames = {"Matrix": exact, "src": source}
    snapshot = dict(frames)
    with pytest.raises(AxisMappingError):
        reconstruct_grouped_matrix(
            frames,
            table="Matrix",
            output="mtx",
            row_keys=["row_id"],
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )
    assert frames == snapshot
    assert "mtx" not in frames


def test_exactly_one_mapping_resolution(monkeypatch):
    gm, source = _grouped_matrix()
    exact = grouped_matrix_to_exact_table(gm)
    calls = {"n": 0}
    real = grouped_xref.reconstruction.resolve_axis_mapping

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(grouped_xref.reconstruction, "resolve_axis_mapping", counting)
    _reconstruct(exact, source)
    assert calls["n"] == 1


def test_drop_source_removes_input_frame():
    gm, source = _grouped_matrix()
    exact = grouped_matrix_to_exact_table(gm)
    out = _reconstruct(exact, source, drop_source=True)
    assert "Matrix" not in out
    assert isinstance(out["mtx"], GroupedMatrix)
