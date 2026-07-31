"""Contract tests for the GX-2 grouped-XRef composites.

GX-2 of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. These prove the two public composites
(`contract_grouped_xref` / `expand_grouped_xref`) compose unchanged XRef with the
accepted GX-1 primitives around the trusted `GroupedMatrix` carrier: exact dense
roundtrip, single mapping resolution with forward completeness, structural
pairing safety, XRef-owned metadata, `drop_source` atomicity, and safe
composite diagnostics. XRef shape conversion and the resolver bijection are proven
elsewhere and relied upon here, not reasserted.
"""
from __future__ import annotations

import copy
import inspect

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.xref_axis_mapping import (
    AxisMappingError,
)
from spreadsheet_handling.domain.transformations.grouped_xref import (
    DynamicColumn,
    GroupedHeader,
    GroupedHeaderError,
    GroupedMatrix,
    GroupedXrefError,
    RowKeyColumn,
    contract_grouped_xref,
    expand_grouped_xref,
)

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

_KEYS2 = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")


def _dense_relation(row_ids: tuple[str, ...] = ("r1", "r2")) -> pd.DataFrame:
    """A *dense* relation: every (row, key) pair present, so the contract/expand
    roundtrip is exact (no XRef ``fill_value`` densification of missing cells)."""
    rows = [
        {"row_id": rid, "column_key": key, "value": f"{rid}:{key}"}
        for rid in row_ids
        for key in _KEYS2
    ]
    return pd.DataFrame(rows)


def _source2() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "key": list(_KEYS2),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitätendarlehen", "Festzinsdarlehen", "Guthaben"],
        }
    )


def _frames() -> dict[str, object]:
    return {"rel": _dense_relation(), "src": _source2()}


def _forward(frames: dict[str, object], **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = dict(
        relation="rel",
        output="mtx",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    kwargs.update(overrides)
    return contract_grouped_xref(frames, **kwargs)  # type: ignore[arg-type]


def _sorted(relation: pd.DataFrame) -> pd.DataFrame:
    return relation.sort_values(["row_id", "column_key"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# GroupedMatrix carrier                                                        #
# --------------------------------------------------------------------------- #

def test_carrier_validates_frame_and_header_types() -> None:
    header = GroupedHeader(
        level_names=("grp", "leaf"),
        columns=(RowKeyColumn(label="row_id", position=0),),
    )
    with pytest.raises(GroupedXrefError):
        GroupedMatrix(frame=[1, 2, 3], header=header)  # type: ignore[arg-type]
    with pytest.raises(GroupedXrefError):
        GroupedMatrix(frame=pd.DataFrame({"row_id": [1]}), header=object())  # type: ignore[arg-type]


def test_carrier_has_identity_semantics_not_value_equality() -> None:
    header = GroupedHeader(
        level_names=("grp", "leaf"),
        columns=(RowKeyColumn(label="row_id", position=0),),
    )
    frame = pd.DataFrame({"row_id": [1]})
    a = GroupedMatrix(frame=frame, header=header)
    b = GroupedMatrix(frame=frame, header=header)
    # Same content, distinct instances: NOT equal (identity semantics, not a
    # value object), and hashable only by identity.
    assert a == a
    assert a != b
    assert hash(a) == hash(a)
    assert hash(a) != hash(b)


# --------------------------------------------------------------------------- #
# Forward composite                                                            #
# --------------------------------------------------------------------------- #

def test_forward_publishes_one_grouped_matrix_with_exact_descriptor() -> None:
    frames = _frames()
    out = _forward(frames, level_names=["Kategorie", "Produkt"])
    grouped = out["mtx"]
    assert isinstance(grouped, GroupedMatrix)
    header = grouped.header
    assert header.level_names == ("Kategorie", "Produkt")
    # row-key column first, then one dynamic column per canonical key in matrix order
    assert type(header.columns[0]) is RowKeyColumn
    dynamic = {c.labels for c in header.columns if type(c) is DynamicColumn}
    assert dynamic == {
        ("Kredit", "Annuitätendarlehen"),
        ("Kredit", "Festzinsdarlehen"),
        ("Einlage", "Guthaben"),
    }


def test_forward_flat_frame_keeps_canonical_string_headers() -> None:
    out = _forward(_frames())
    flat = out["mtx"].frame
    assert list(flat.columns) == ["row_id", *_KEYS2]
    assert not isinstance(flat.columns, pd.MultiIndex)


def test_forward_introduces_no_private_frame() -> None:
    frames = _frames()
    out = _forward(frames)
    assert set(out) == {"rel", "src", "mtx", "_meta"}


def test_forward_does_not_mutate_caller_frames_or_meta() -> None:
    frames = _frames()
    snapshot = copy.deepcopy(frames)
    _forward(frames)
    assert set(frames) == {"rel", "src"}
    assert "_meta" not in frames
    for name, df in snapshot.items():
        pd.testing.assert_frame_equal(frames[name], df)


def test_forward_used_keys_completeness_rejects_missing_source_key() -> None:
    frames = _frames()
    # Drop a canonical key from the source so a matrix dynamic header is missing.
    frames["src"] = _source2().iloc[:2].reset_index(drop=True)
    with pytest.raises(AxisMappingError):
        _forward(frames)


def test_forward_missing_source_frame_rejected() -> None:
    frames = {"rel": _dense_relation()}
    with pytest.raises(AxisMappingError):
        _forward(frames)


def test_forward_rejects_drop_source_into_same_output() -> None:
    with pytest.raises(GroupedXrefError):
        _forward(_frames(), output="rel", drop_source=True)


# --------------------------------------------------------------------------- #
# Metadata / name ownership                                                    #
# --------------------------------------------------------------------------- #

def test_forward_metadata_is_xref_owned_with_public_names_only() -> None:
    out = _forward(_frames())
    meta = out["_meta"]
    # No grouped-XRef metadata root; only XRef's own root.
    assert set(meta) == {"xref_crosstable"}
    configs = meta["xref_crosstable"]
    assert set(configs) == {"rel"}  # config id == relation when name is None
    payload = configs["rel"]
    assert payload["relation"] == "rel" and payload["matrix"] == "mtx"
    # Only caller-supplied public frame names appear.
    assert "mtx" in (payload["matrix"],)


def test_forward_name_becomes_xref_config_id() -> None:
    out = _forward(_frames(), name="my_axis")
    assert set(out["_meta"]["xref_crosstable"]) == {"my_axis"}


# --------------------------------------------------------------------------- #
# Atomicity                                                                    #
# --------------------------------------------------------------------------- #

def test_failure_after_xref_before_publication_leaves_caller_unchanged() -> None:
    frames = _frames()
    snapshot = copy.deepcopy(frames)
    # ``level_names`` of the wrong length fails inside build_grouped_header, i.e.
    # strictly after contract_xref produced its (discardable) interim copy.
    with pytest.raises(GroupedHeaderError):
        _forward(frames, level_names=["only_one_level"])
    assert set(frames) == {"rel", "src"}
    assert "_meta" not in frames
    for name, df in snapshot.items():
        pd.testing.assert_frame_equal(frames[name], df)


# --------------------------------------------------------------------------- #
# Inverse composite                                                            #
# --------------------------------------------------------------------------- #

def test_inverse_restores_canonical_relation_exact_dense_roundtrip() -> None:
    frames = _frames()
    forward = _forward(frames)
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": frames["src"]},
        matrix="mtx",
        output="rel_out",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    pd.testing.assert_frame_equal(
        _sorted(inverse["rel_out"]), _sorted(_dense_relation())
    )


def test_inverse_requires_grouped_matrix_carrier() -> None:
    frames = {"mtx": _dense_relation(), "src": _source2()}
    with pytest.raises(GroupedXrefError):
        expand_grouped_xref(
            frames,
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_inverse_missing_matrix_frame_rejected() -> None:
    with pytest.raises(GroupedXrefError):
        expand_grouped_xref(
            {"src": _source2()},
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_inverse_exposes_no_descriptor_parameter() -> None:
    params = set(inspect.signature(expand_grouped_xref).parameters)
    assert "header" not in params
    assert "descriptor" not in params
    assert "grouped_header" not in params


def test_inverse_keeps_grouped_matrix_when_not_dropping_source() -> None:
    frames = _frames()
    forward = _forward(frames)
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": frames["src"]},
        matrix="mtx",
        output="rel_out",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    # The grouped representation is preserved under ``matrix`` (not the transient
    # unwrapped flat frame).
    assert isinstance(inverse["mtx"], GroupedMatrix)


def test_mapping_drift_between_forward_and_inverse_is_rejected() -> None:
    frames = _frames()
    forward = _forward(frames)
    # The source changes one leaf label after the grouped matrix was built; the
    # descriptor still carries the old visible tuple, which no longer resolves.
    drifted = _source2()
    drifted.loc[drifted["key"] == "deposit.balance", "leaf"] = "Sichteinlage"
    with pytest.raises(AxisMappingError):
        expand_grouped_xref(
            {"mtx": forward["mtx"], "src": drifted},
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_inverse_rejects_drop_source_into_same_output() -> None:
    frames = _frames()
    forward = _forward(frames)
    with pytest.raises(GroupedXrefError):
        expand_grouped_xref(
            {"mtx": forward["mtx"], "src": frames["src"]},
            matrix="mtx",
            output="mtx",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
            drop_source=True,
        )


# --------------------------------------------------------------------------- #
# drop_source                                                                  #
# --------------------------------------------------------------------------- #

def test_forward_drop_source_marks_relation_for_cleanup() -> None:
    out = _forward(_frames(), drop_source=True)
    assert out["_meta"]["pipeline_cleanup"]["drop_frames"] == ["rel"]


def test_inverse_drop_source_marks_matrix_for_cleanup() -> None:
    frames = _frames()
    forward = _forward(frames)
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": frames["src"]},
        matrix="mtx",
        output="rel_out",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
        drop_source=True,
    )
    assert inverse["_meta"]["pipeline_cleanup"]["drop_frames"] == ["mtx"]


# --------------------------------------------------------------------------- #
# Order policy independence                                                    #
# --------------------------------------------------------------------------- #

def test_roundtrip_identical_under_both_order_policies() -> None:
    def run(order_policy: str, order_columns: tuple[str, ...]) -> pd.DataFrame:
        source = _source2()
        source["ord"] = [2, 1, 3]
        frames = {"rel": _dense_relation(), "src": source}
        forward = contract_grouped_xref(
            frames,
            relation="rel",
            output="mtx",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
            order_policy=order_policy,
            order_columns=order_columns,
        )
        inverse = expand_grouped_xref(
            {"mtx": forward["mtx"], "src": source},
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
            order_policy=order_policy,
            order_columns=order_columns,
        )
        return _sorted(inverse["rel_out"])

    by_row = run("source_row", ())
    by_cols = run("columns", ("ord",))
    pd.testing.assert_frame_equal(by_row, by_cols)
    pd.testing.assert_frame_equal(by_row, _sorted(_dense_relation()))


# --------------------------------------------------------------------------- #
# Arity 3, repeated upper levels, literal delimiters                          #
# --------------------------------------------------------------------------- #

def test_roundtrip_arity_three_repeated_upper_and_literal_delimiters() -> None:
    keys = ("k.a", "k.b", "k.c")
    # Repeated upper/middle labels with distinct complete tuples, and literal
    # " / " and "." inside components -- must survive with no split/join.
    source = pd.DataFrame(
        {
            "key": list(keys),
            "top": ["Group / One", "Group / One", "Group / Two"],
            "mid": ["M.1", "M.1", "M.2"],
            "leaf": ["Leaf A", "Leaf B", "Leaf C"],
        }
    )
    relation = pd.DataFrame(
        [
            {"row_id": rid, "column_key": key, "value": f"{rid}:{key}"}
            for rid in ("r1", "r2")
            for key in keys
        ]
    )
    frames = {"rel": relation, "src": source}
    forward = contract_grouped_xref(
        frames,
        relation="rel",
        output="mtx",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["top", "mid", "leaf"],
    )
    header = forward["mtx"].header
    assert header.arity == 3
    labels = {c.labels for c in header.columns if type(c) is DynamicColumn}
    assert ("Group / One", "M.1", "Leaf A") in labels
    assert ("Group / One", "M.1", "Leaf B") in labels
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": source},
        matrix="mtx",
        output="rel_out",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["top", "mid", "leaf"],
    )
    pd.testing.assert_frame_equal(
        _sorted(inverse["rel_out"]),
        relation.sort_values(["row_id", "column_key"]).reset_index(drop=True),
    )
