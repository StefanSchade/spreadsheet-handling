"""Contract tests for the GX-1 grouped-header model and projection primitives.

Boundary behaviour owned by GX-1 only. The Slice 1 resolver's key/label
bijection internals are proven by ``test_xref_axis_mapping.py`` and are relied
upon here, not reasserted.
"""
from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.xref_axis_mapping import (
    AxisMappingError,
    AxisMappingIntent,
    AxisOrderPolicy,
    ResolvedAxisMapping,
    resolve_axis_mapping,
)
from spreadsheet_handling.domain.transformations.grouped_xref import (
    DynamicColumn,
    GroupedHeader,
    GroupedHeaderError,
    RowKeyColumn,
    build_grouped_header,
    restore_flat_matrix,
)

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")


class _ExplosiveEquality:
    """A hostile object whose comparison/representation must never be invoked."""

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("do not leak")

    def __hash__(self) -> int:
        return 0

    def __repr__(self) -> str:
        raise RuntimeError("do not leak")


def _mapping(
    *,
    keys: tuple[str, ...],
    labels: tuple[tuple[str, ...], ...],
    label_columns: tuple[str, ...],
    order_policy: AxisOrderPolicy = AxisOrderPolicy.SOURCE_ROW,
    order_columns: tuple[str, ...] = (),
    order_values: tuple[object, ...] | None = None,
) -> ResolvedAxisMapping:
    data: dict[str, list[object]] = {"key": list(keys)}
    for index, name in enumerate(label_columns):
        data[name] = [row[index] for row in labels]
    for name in order_columns:
        assert order_values is not None
        data[name] = list(order_values)
    intent = AxisMappingIntent(
        source_frame="axis",
        key_column="key",
        label_columns=label_columns,
        order_policy=order_policy,
        order_columns=order_columns,
    )
    return resolve_axis_mapping({"axis": pd.DataFrame(data)}, intent)


def _arity2() -> ResolvedAxisMapping:
    # Repeated upper-level label ("Kredit") with distinct complete tuples, plus
    # literal " / " and "." characters inside components.
    return _mapping(
        keys=("credit.annuity", "credit.bullet", "deposit.call"),
        labels=(
            ("Kredit", "Annuität"),
            ("Kredit", "Endf.al"),
            ("Einlage / Spar", "Tagesgeld"),
        ),
        label_columns=("fam", "lab"),
    )


def _flat2(index: object = None) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "row_id": ["r1", "r2"],
            "credit.annuity": [1, 2],
            "credit.bullet": [3, 4],
            "deposit.call": [5, 6],
        }
    )
    if index is not None:
        frame.index = pd.Index(index)
    return frame


# --------------------------------------------------------------------------- #
# Model: construction, immutability, equality, ownership
# --------------------------------------------------------------------------- #


def test_model_construction_and_positions() -> None:
    header = GroupedHeader(
        level_names=("fam", "lab"),
        columns=(
            RowKeyColumn(label="row_id", position=0),
            DynamicColumn(labels=("Kredit", "Annuität"), position=1),
        ),
    )
    assert header.arity == 2
    assert header.level_names == ("fam", "lab")
    assert isinstance(header.columns, tuple)


def test_model_is_frozen_and_hashable_with_value_equality() -> None:
    a = GroupedHeader(
        level_names=("fam", "lab"),
        columns=(DynamicColumn(labels=("Kredit", "Annuität"), position=0),),
    )
    b = GroupedHeader(
        level_names=("fam", "lab"),
        columns=(DynamicColumn(labels=("Kredit", "Annuität"), position=0),),
    )
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1
    with pytest.raises(FrozenInstanceError):
        a.level_names = ("x",)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        a.columns[0].position = 5  # type: ignore[misc]


def test_model_copies_caller_sequences_into_owned_tuples() -> None:
    level_names = ["fam", "lab"]
    columns = [DynamicColumn(labels=("Kredit", "Annuität"), position=0)]
    header = GroupedHeader(level_names=level_names, columns=columns)
    level_names.append("mutated")
    columns.append(DynamicColumn(labels=("x", "y"), position=1))
    assert header.level_names == ("fam", "lab")
    assert len(header.columns) == 1
    assert isinstance(header.level_names, tuple)
    assert isinstance(header.columns, tuple)


def test_model_rejects_non_contiguous_positions() -> None:
    with pytest.raises(GroupedHeaderError):
        GroupedHeader(
            level_names=("fam",),
            columns=(DynamicColumn(labels=("Kredit",), position=1),),
        )


def test_model_rejects_arity_mismatch() -> None:
    with pytest.raises(GroupedHeaderError):
        GroupedHeader(
            level_names=("fam", "lab"),
            columns=(DynamicColumn(labels=("Kredit",), position=0),),
        )


def test_model_rejects_foreign_column_type() -> None:
    with pytest.raises(GroupedHeaderError):
        GroupedHeader(level_names=("fam",), columns=(object(),))  # type: ignore[arg-type]


def test_model_rejects_empty_duplicate_and_wrong_typed_level_names() -> None:
    with pytest.raises(GroupedHeaderError):
        GroupedHeader(level_names=(), columns=())
    with pytest.raises(GroupedHeaderError):
        GroupedHeader(level_names=("fam", "fam"), columns=())
    with pytest.raises(GroupedHeaderError):
        GroupedHeader(level_names=("fam", ""), columns=())
    with pytest.raises(GroupedHeaderError):
        GroupedHeader(level_names=("fam", 3), columns=())  # type: ignore[arg-type]


def test_dynamic_column_requires_exact_tuple_and_position() -> None:
    with pytest.raises(GroupedHeaderError):
        DynamicColumn(labels=["Kredit"], position=0)  # type: ignore[arg-type]
    with pytest.raises(GroupedHeaderError):
        DynamicColumn(labels=(), position=0)
    with pytest.raises(GroupedHeaderError):
        DynamicColumn(labels=("Kredit",), position=-1)


# --------------------------------------------------------------------------- #
# Forward: classification, level-name defaulting
# --------------------------------------------------------------------------- #


def test_forward_classifies_row_key_and_dynamic_columns() -> None:
    header = build_grouped_header(_flat2(), row_keys="row_id", mapping=_arity2())
    assert header.level_names == ("fam", "lab")
    assert header.columns[0] == RowKeyColumn(label="row_id", position=0)
    assert header.columns[1] == DynamicColumn(labels=("Kredit", "Annuität"), position=1)
    assert header.columns[3] == DynamicColumn(
        labels=("Einlage / Spar", "Tagesgeld"), position=3
    )


def test_forward_level_names_default_to_label_columns() -> None:
    header = build_grouped_header(_flat2(), row_keys=["row_id"], mapping=_arity2())
    assert header.level_names == ("fam", "lab")


def test_forward_explicit_level_names_and_wrong_length() -> None:
    header = build_grouped_header(
        _flat2(), row_keys="row_id", mapping=_arity2(), level_names=("group", "leaf")
    )
    assert header.level_names == ("group", "leaf")
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(
            _flat2(), row_keys="row_id", mapping=_arity2(), level_names=("only",)
        )


def test_forward_bare_string_and_multiple_row_keys() -> None:
    frame = pd.DataFrame(
        {"a": ["x"], "b": ["y"], "credit.annuity": [1]}
    )
    header = build_grouped_header(frame, row_keys=["a", "b"], mapping=_arity2())
    assert header.columns[0] == RowKeyColumn(label="a", position=0)
    assert header.columns[1] == RowKeyColumn(label="b", position=1)
    assert header.columns[2].__class__ is DynamicColumn

    single = build_grouped_header(_flat2(), row_keys="row_id", mapping=_arity2())
    assert isinstance(single.columns[0], RowKeyColumn)


def test_forward_row_key_precedence_over_would_be_dynamic_key() -> None:
    # "credit.annuity" is also a valid canonical key, but declaring it as a row
    # key classifies it as a row-key column, not a dynamic one.
    header = build_grouped_header(
        _flat2(), row_keys=["row_id", "credit.annuity"], mapping=_arity2()
    )
    assert header.columns[1] == RowKeyColumn(label="credit.annuity", position=1)
    assert all(
        not isinstance(c, DynamicColumn) or c.position != 1 for c in header.columns
    )


def test_forward_missing_and_duplicate_row_keys() -> None:
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(_flat2(), row_keys="absent", mapping=_arity2())
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(
            _flat2(), row_keys=["row_id", "row_id"], mapping=_arity2()
        )
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(_flat2(), row_keys=[], mapping=_arity2())


def test_forward_rejects_unknown_canonical_key() -> None:
    frame = pd.DataFrame({"row_id": ["r1"], "unknown.key": [1]})
    with pytest.raises(AxisMappingError):
        build_grouped_header(frame, row_keys="row_id", mapping=_arity2())


def test_forward_rejects_multiindex_tuple_duplicate_nonstring_empty_headers() -> None:
    multi = pd.DataFrame([[1, 2]])
    multi.columns = pd.MultiIndex.from_tuples([("row_id", ""), ("credit", "annuity")])
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(multi, row_keys="row_id", mapping=_arity2())

    tup = pd.DataFrame([[1, 2]])
    tup.columns = pd.Index([("row_id",), ("credit", "annuity")], tupleize_cols=False)
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(tup, row_keys="row_id", mapping=_arity2())

    dup = pd.DataFrame([[1, 2, 3]])
    dup.columns = ["row_id", "credit.annuity", "credit.annuity"]
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(dup, row_keys="row_id", mapping=_arity2())

    nonstring = pd.DataFrame({"row_id": ["r1"], 7: [1]})
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(nonstring, row_keys="row_id", mapping=_arity2())

    empty = pd.DataFrame({"row_id": ["r1"], "  ": [1]})
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(empty, row_keys="row_id", mapping=_arity2())


def test_forward_does_not_mutate_frame_or_row_keys() -> None:
    frame = _flat2()
    snapshot = frame.copy(deep=True)
    row_keys = ["row_id"]
    build_grouped_header(frame, row_keys=row_keys, mapping=_arity2())
    assert frame.equals(snapshot)
    assert list(frame.columns) == list(snapshot.columns)
    assert row_keys == ["row_id"]


def test_forward_safe_diagnostics_with_explosive_header() -> None:
    frame = pd.DataFrame([[1, 2]])
    frame.columns = ["row_id", _ExplosiveEquality()]
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(frame, row_keys="row_id", mapping=_arity2())


# --------------------------------------------------------------------------- #
# Inverse + roundtrip
# --------------------------------------------------------------------------- #


def test_inverse_restores_canonical_headers() -> None:
    header = build_grouped_header(_flat2(), row_keys="row_id", mapping=_arity2())
    restored = restore_flat_matrix(_flat2(), header, mapping=_arity2())
    assert list(restored.columns) == [
        "row_id",
        "credit.annuity",
        "credit.bullet",
        "deposit.call",
    ]


def test_exact_roundtrip_preserves_data_index_and_order() -> None:
    flat = _flat2(index=[10, 7])  # non-monotonic, non-default index
    header = build_grouped_header(flat, row_keys="row_id", mapping=_arity2())
    restored = restore_flat_matrix(flat, header, mapping=_arity2())
    assert restored.equals(flat)
    assert list(restored.columns) == list(flat.columns)
    assert restored.index.tolist() == [10, 7]


@pytest.mark.parametrize(
    "order_policy,order_columns,order_values",
    [
        (AxisOrderPolicy.SOURCE_ROW, (), None),
        (AxisOrderPolicy.COLUMNS, ("ord",), (3, 1, 2)),
    ],
)
def test_roundtrip_independent_of_order_policy(
    order_policy: AxisOrderPolicy,
    order_columns: tuple[str, ...],
    order_values: tuple[object, ...] | None,
) -> None:
    mapping = _mapping(
        keys=("credit.annuity", "credit.bullet", "deposit.call"),
        labels=(("Kredit", "Annuität"), ("Kredit", "Endf.al"), ("Einlage / Spar", "Tagesgeld")),
        label_columns=("fam", "lab"),
        order_policy=order_policy,
        order_columns=order_columns,
        order_values=order_values,
    )
    flat = _flat2()
    header = build_grouped_header(flat, row_keys="row_id", mapping=mapping)
    restored = restore_flat_matrix(flat, header, mapping=mapping)
    assert restored.equals(flat)


def test_roundtrip_arity_three_with_repeated_upper_levels() -> None:
    mapping = _mapping(
        keys=("a", "b", "c"),
        labels=(
            ("Top", "Mid", "Leaf1"),
            ("Top", "Mid", "Leaf2"),
            ("Top", "Other", "Leaf3"),
        ),
        label_columns=("l1", "l2", "l3"),
    )
    flat = pd.DataFrame({"row_id": ["r"], "a": [1], "b": [2], "c": [3]})
    header = build_grouped_header(flat, row_keys="row_id", mapping=mapping)
    assert header.arity == 3
    assert header.columns[1] == DynamicColumn(labels=("Top", "Mid", "Leaf1"), position=1)
    restored = restore_flat_matrix(flat, header, mapping=mapping)
    assert restored.equals(flat)


def test_roundtrip_preserves_shuffled_physical_column_order() -> None:
    flat = pd.DataFrame(
        {
            "credit.annuity": [1],
            "row_id": ["r1"],
            "deposit.call": [5],
        }
    )
    header = build_grouped_header(flat, row_keys="row_id", mapping=_arity2())
    assert [type(c).__name__ for c in header.columns] == [
        "DynamicColumn",
        "RowKeyColumn",
        "DynamicColumn",
    ]
    restored = restore_flat_matrix(flat, header, mapping=_arity2())
    assert list(restored.columns) == ["credit.annuity", "row_id", "deposit.call"]


# --------------------------------------------------------------------------- #
# Inverse failures + atomicity
# --------------------------------------------------------------------------- #


def test_inverse_rejects_unknown_wrong_arity_and_incomplete_tuples() -> None:
    frame = _flat2()
    unknown = GroupedHeader(
        level_names=("fam", "lab"),
        columns=(
            RowKeyColumn(label="row_id", position=0),
            DynamicColumn(labels=("Kredit", "Annuität"), position=1),
            DynamicColumn(labels=("No", "Such"), position=2),
            DynamicColumn(labels=("Einlage / Spar", "Tagesgeld"), position=3),
        ),
    )
    with pytest.raises(AxisMappingError):
        restore_flat_matrix(frame, unknown, mapping=_arity2())

    wrong_arity = GroupedHeader(
        level_names=("only",),
        columns=(
            RowKeyColumn(label="row_id", position=0),
            DynamicColumn(labels=("Kredit",), position=1),
            DynamicColumn(labels=("Kredit",), position=2),
            DynamicColumn(labels=("Einlage / Spar",), position=3),
        ),
    )
    with pytest.raises(AxisMappingError):
        restore_flat_matrix(frame, wrong_arity, mapping=_arity2())


def test_inverse_rejects_duplicate_complete_tuple() -> None:
    frame = _flat2()
    header = GroupedHeader(
        level_names=("fam", "lab"),
        columns=(
            RowKeyColumn(label="row_id", position=0),
            DynamicColumn(labels=("Kredit", "Annuität"), position=1),
            DynamicColumn(labels=("Kredit", "Annuität"), position=2),
            DynamicColumn(labels=("Einlage / Spar", "Tagesgeld"), position=3),
        ),
    )
    with pytest.raises(GroupedHeaderError):
        restore_flat_matrix(frame, header, mapping=_arity2())


def test_inverse_rejects_row_key_dynamic_collision() -> None:
    frame = _flat2()
    header = GroupedHeader(
        level_names=("fam", "lab"),
        columns=(
            RowKeyColumn(label="credit.annuity", position=0),
            DynamicColumn(labels=("Kredit", "Annuität"), position=1),
            DynamicColumn(labels=("Kredit", "Endf.al"), position=2),
            DynamicColumn(labels=("Einlage / Spar", "Tagesgeld"), position=3),
        ),
    )
    with pytest.raises(GroupedHeaderError):
        restore_flat_matrix(frame, header, mapping=_arity2())


def test_inverse_rejects_descriptor_dataframe_mismatch() -> None:
    header = build_grouped_header(_flat2(), row_keys="row_id", mapping=_arity2())
    short = pd.DataFrame({"row_id": ["r1"], "credit.annuity": [1]})
    with pytest.raises(GroupedHeaderError):
        restore_flat_matrix(short, header, mapping=_arity2())


def test_inverse_does_not_mutate_input_frame() -> None:
    flat = _flat2()
    snapshot = flat.copy(deep=True)
    header = build_grouped_header(flat, row_keys="row_id", mapping=_arity2())
    result = restore_flat_matrix(flat, header, mapping=_arity2())
    assert flat.equals(snapshot)
    assert list(flat.columns) == list(snapshot.columns)
    result.iloc[0, 1] = 999
    assert flat.equals(snapshot)


def test_inverse_atomic_on_failure() -> None:
    frame = _flat2()
    before = frame.copy(deep=True)
    unknown = GroupedHeader(
        level_names=("fam", "lab"),
        columns=(
            RowKeyColumn(label="row_id", position=0),
            DynamicColumn(labels=("Kredit", "Annuität"), position=1),
            DynamicColumn(labels=("Kredit", "Endf.al"), position=2),
            DynamicColumn(labels=("No", "Such"), position=3),
        ),
    )
    with pytest.raises(AxisMappingError):
        restore_flat_matrix(frame, unknown, mapping=_arity2())
    assert frame.equals(before)


# --------------------------------------------------------------------------- #
# Input-type guards
# --------------------------------------------------------------------------- #


def test_primitives_reject_non_dataframe_and_non_mapping() -> None:
    header = build_grouped_header(_flat2(), row_keys="row_id", mapping=_arity2())
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(["not", "a", "frame"], row_keys="row_id", mapping=_arity2())  # type: ignore[arg-type]
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(_flat2(), row_keys="row_id", mapping=object())  # type: ignore[arg-type]
    with pytest.raises(GroupedHeaderError):
        restore_flat_matrix(object(), header, mapping=_arity2())  # type: ignore[arg-type]
    with pytest.raises(GroupedHeaderError):
        restore_flat_matrix(_flat2(), object(), mapping=_arity2())  # type: ignore[arg-type]


def test_explosive_object_is_never_compared_during_forward() -> None:
    # A deep copy proves the fixture itself is inert to copy; the projection must
    # reject it without invoking __eq__/__repr__ (which would raise RuntimeError).
    explosive = _ExplosiveEquality()
    copy.copy(explosive)
    frame = pd.DataFrame([[1, 2]])
    frame.columns = ["row_id", explosive]
    with pytest.raises(GroupedHeaderError):
        build_grouped_header(frame, row_keys="row_id", mapping=_arity2())
