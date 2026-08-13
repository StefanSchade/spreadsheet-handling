"""Focused contract tests for Trusted Ingress Phase-E slice E2."""

from __future__ import annotations

import copy
import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest

from spreadsheet_handling.core.exact_table import ExactTable
from spreadsheet_handling.core.formulas import lookup_formula
from spreadsheet_handling.domain.ingress import structural_admission
from spreadsheet_handling.domain.ingress.structural_admission import (
    OrdinaryStructureAdmissionError,
    admit_ordinary_frames,
)
from spreadsheet_handling.domain.transformations.grouped_xref import (
    GroupedMatrix,
    contract_grouped_xref,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


class _FramesSubclass(dict[str, object]):
    pass


def _exact_table(
    *,
    header_grid: tuple[tuple[Any, ...], ...] = (("left", "right"),),
    data: tuple[tuple[Any, ...], ...] = ((1, "a"), (2, "b")),
    header_rows: Any = 1,
    n_cols: Any = 2,
) -> ExactTable:
    """Forge an exact carrier when a test must bypass its coercing constructor."""
    table = object.__new__(ExactTable)
    object.__setattr__(table, "header_grid", header_grid)
    object.__setattr__(table, "data", data)
    object.__setattr__(table, "header_rows", header_rows)
    object.__setattr__(table, "n_cols", n_cols)
    return table


def _grouped_matrix() -> GroupedMatrix:
    source = pd.DataFrame(
        {
            "key": ["credit", "deposit"],
            "group": ["Liability", "Asset"],
            "label": ["Loan", "Savings"],
        }
    )
    relation = pd.DataFrame(
        [
            {"row_id": row_id, "column_key": key, "value": value}
            for row_id, values in (("r1", (1, 2)), ("r2", (3, 4)))
            for key, value in zip(("credit", "deposit"), values, strict=True)
        ]
    )
    result = contract_grouped_xref(
        {"relation": relation, "source": source},
        relation="relation",
        output="matrix",
        row_keys=["row_id"],
        source_frame="source",
        key_column="key",
        label_columns=["group", "label"],
    )
    grouped = result["matrix"]
    assert type(grouped) is GroupedMatrix
    return grouped


def _assert_error(
    excinfo: pytest.ExceptionInfo[OrdinaryStructureAdmissionError],
    *,
    kind: str,
    carrier_role: str,
    frame_ordinal: int | None,
    frame_name: str | None,
    row_ordinal: int | None = None,
    column_ordinal: int | None = None,
) -> None:
    error = excinfo.value
    assert error.kind == kind
    assert error.carrier_role == carrier_role
    assert error.frame_ordinal == frame_ordinal
    assert error.frame_name == frame_name
    assert error.row_ordinal == row_ordinal
    assert error.column_ordinal == column_ordinal
    assert vars(error) == {
        "kind": kind,
        "carrier_role": carrier_role,
        "frame_ordinal": frame_ordinal,
        "frame_name": frame_name,
        "row_ordinal": row_ordinal,
        "column_ordinal": column_ordinal,
    }


def test_multiple_frames_dtypes_and_exact_table_are_admitted_by_identity() -> None:
    integers = pd.DataFrame({"n": pd.Series([1, 2], dtype="int64")})
    mixed = pd.DataFrame(
        {
            "text": pd.Series(["a", "b"], dtype="string"),
            "flag": pd.Series([True, False], dtype="bool"),
            "when": [datetime.date(2026, 8, 12), datetime.date(2026, 8, 13)],
        }
    )
    exact = ExactTable(
        header_grid=(("value",),),
        data=((pd.Timestamp("2026-08-13"),),),
        header_rows=1,
        n_cols=1,
    )
    metadata = {"unvalidated_until_e3": [{"nested": object()}]}
    frames = {"integers": integers, "mixed": mixed, "exact": exact, "_meta": metadata}

    admitted = admit_ordinary_frames(frames)

    assert admitted is frames
    assert admitted["integers"] is integers
    assert admitted["mixed"] is mixed
    assert admitted["exact"] is exact
    assert admitted["_meta"] is metadata


def test_empty_dataframe_is_admitted() -> None:
    frame = pd.DataFrame(columns=["a", 7])
    frames = {"empty": frame}

    assert admit_ordinary_frames(frames) is frames
    assert frames["empty"] is frame


def test_every_cell_is_visited_positionally_in_mapping_and_row_major_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visited: list[object] = []
    first = pd.DataFrame([["a00", "a01"], ["a10", "a11"]], columns=["x", "y"])
    second = pd.DataFrame([["b00"], ["b10"]], columns=["z"])
    exact = ExactTable(
        header_grid=(("e",),),
        data=(("e00",), ("e10",)),
        header_rows=1,
        n_cols=1,
    )

    def record(value: object) -> object:
        visited.append(value)
        return value

    monkeypatch.setattr(structural_admission, "admit_ordinary_scalar", record)

    admit_ordinary_frames({"first": first, "second": second, "exact": exact})

    assert visited == ["a00", "a01", "a10", "a11", "b00", "b10", "e00", "e10"]


def test_late_dataframe_cell_rejects_with_safe_deterministic_ordinals() -> None:
    first = pd.DataFrame({"ok": [1, 2]})
    second = pd.DataFrame([["ok", 1], ["still ok", object()]], columns=["a", "b"])

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"first": first, "second": second})

    _assert_error(
        excinfo,
        kind="unsupported_scalar_carrier",
        carrier_role="dataframe",
        frame_ordinal=1,
        frame_name="second",
        row_ordinal=1,
        column_ordinal=1,
    )
    assert str(excinfo.value) == (
        "ordinary structural admission failed (unsupported_scalar_carrier) at "
        "carrier role dataframe, frame ordinal 1, frame name 'second', "
        "row ordinal 1, column ordinal 1"
    )
    assert excinfo.value.__cause__ is None


def test_failure_leaves_complete_caller_graph_unchanged() -> None:
    formula = lookup_formula(
        source_key_column="key",
        lookup_sheet="source",
        lookup_key_column="id",
        lookup_value_column="label",
    )
    frame = pd.DataFrame([[1, "ok"], [2, formula]], columns=["id", "value"])
    metadata = {"legend_blocks": {"sheet": [{"title": "untouched"}]}}
    frames = {"data": frame, "_meta": metadata}
    frame_before = frame.copy(deep=True)
    metadata_before = copy.deepcopy(metadata)
    keys_before = tuple(frames)

    with pytest.raises(OrdinaryStructureAdmissionError):
        admit_ordinary_frames(frames)

    assert tuple(frames) == keys_before
    assert frames["data"] is frame
    assert frames["_meta"] is metadata
    pd.testing.assert_frame_equal(frame, frame_before)
    assert metadata == metadata_before
    assert frame.iat[1, 1] is formula


@pytest.mark.parametrize(
    "columns",
    [
        ["a", "b"],
        [1, 2],
        pd.Index([("a", "left"), ("b", "right")], tupleize_cols=False),
    ],
    ids=["strings", "numeric", "hashable-tuples"],
)
def test_current_valid_physical_column_authority_is_preserved(columns: object) -> None:
    frame = pd.DataFrame([[1, 2]], columns=columns)

    assert admit_ordinary_frames({"frame": frame})["frame"] is frame


@pytest.mark.parametrize(
    "columns",
    [
        pd.Index(["a", np.nan], dtype=object),
        pd.Index(["a", pd.NA], dtype=object),
        pd.Index(["a", [1, 2]], dtype=object),
        pd.Index(["a", np.array([1, 2])], dtype=object),
        pd.Index(["a", "a"], dtype=object),
    ],
    ids=["nan", "pandas-na", "unhashable", "ambiguous", "duplicate"],
)
def test_current_invalid_physical_column_authority_is_preserved(columns: pd.Index) -> None:
    frame = pd.DataFrame([[1, 2]], columns=columns)

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"frame": frame})

    _assert_error(
        excinfo,
        kind="invalid_physical_columns",
        carrier_role="dataframe",
        frame_ordinal=0,
        frame_name="frame",
    )


def test_physical_label_failure_does_not_require_label_rendering() -> None:
    calls: list[str] = []

    class _UnhashableLabel:
        def __eq__(self, other: object) -> bool:
            calls.append("eq")
            return self is other

        def __hash__(self) -> int:
            calls.append("hash")
            raise TypeError("not hashable")

        def __repr__(self) -> str:  # pragma: no cover - must never run
            calls.append("repr")
            raise AssertionError("label repr must not run")

    label = _UnhashableLabel()
    frame = pd.DataFrame([[1]], columns=pd.Index([label], dtype=object))
    calls.clear()

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"frame": frame})

    assert excinfo.value.kind == "invalid_physical_columns"
    assert str(excinfo.value).endswith("frame ordinal 0, frame name 'frame'")
    assert "repr" not in calls


def test_duplicate_nonmonotonic_odd_row_indexes_are_traversal_only() -> None:
    odd = object()
    odd_index = pd.Index([("odd", odd), "middle", ("odd", odd)], dtype=object)
    frame = pd.DataFrame({"value": [1, 2, 3]}, index=odd_index)
    original_index = frame.index

    assert admit_ordinary_frames({"frame": frame})["frame"] is frame
    assert frame.index is original_index
    assert frame.index.duplicated().tolist() == [False, False, True]
    assert list(frame["value"]) == [1, 2, 3]


def test_formula_spec_is_rejected_as_an_ordinary_dataframe_cell() -> None:
    formula = lookup_formula(
        source_key_column="key",
        lookup_sheet="source",
        lookup_key_column="id",
        lookup_value_column="label",
    )
    frame = pd.DataFrame([[formula]], columns=["helper"])

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"data": frame})

    _assert_error(
        excinfo,
        kind="unsupported_scalar_carrier",
        carrier_role="dataframe",
        frame_ordinal=0,
        frame_name="data",
        row_ordinal=0,
        column_ordinal=0,
    )


def test_factory_produced_grouped_matrix_is_rejected_as_external_top_level() -> None:
    grouped = _grouped_matrix()

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"matrix": grouped})

    _assert_error(
        excinfo,
        kind="unsupported_top_level_carrier",
        carrier_role="frames",
        frame_ordinal=0,
        frame_name="matrix",
    )


def test_valid_exact_table_geometry_and_cells_are_admitted_by_identity() -> None:
    table = ExactTable(
        header_grid=(("", "Group"), ("id", "value")),
        data=((1, "a"), (2, None)),
        header_rows=2,
        n_cols=2,
    )
    frames = {"exact": table}

    assert admit_ordinary_frames(frames) is frames
    assert frames["exact"] is table


@pytest.mark.parametrize(
    ("field", "invalid", "kind"),
    [
        ("header_rows", True, "invalid_exact_table_header_rows"),
        ("header_rows", -1, "invalid_exact_table_header_rows"),
        ("n_cols", False, "invalid_exact_table_n_cols"),
        ("n_cols", -1, "invalid_exact_table_n_cols"),
    ],
)
def test_exact_table_geometry_requires_nonnegative_exact_integers(
    field: str,
    invalid: object,
    kind: str,
) -> None:
    values = {"header_rows": 1, "n_cols": 2, field: invalid}
    table = _exact_table(
        header_rows=values["header_rows"],
        n_cols=values["n_cols"],
    )

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"exact": table})

    assert excinfo.value.kind == kind


def test_exact_table_header_grid_height_must_match_header_rows() -> None:
    table = _exact_table(header_rows=2)

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"exact": table})

    assert excinfo.value.kind == "invalid_exact_table_header_grid_height"


def test_exact_table_header_row_width_must_match_n_cols() -> None:
    table = _exact_table(header_grid=(("only",),))

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"exact": table})

    _assert_error(
        excinfo,
        kind="invalid_exact_table_header_row_width",
        carrier_role="exact_table",
        frame_ordinal=0,
        frame_name="exact",
        row_ordinal=0,
    )


def test_exact_table_late_data_row_width_must_match_n_cols() -> None:
    table = _exact_table(data=((1, "a"), (2, "b"), (3,)))

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"exact": table})

    _assert_error(
        excinfo,
        kind="invalid_exact_table_data_row_width",
        carrier_role="exact_table",
        frame_ordinal=0,
        frame_name="exact",
        row_ordinal=2,
    )


def test_exact_table_header_cells_must_be_strings() -> None:
    table = _exact_table(header_grid=(("left", 7),))

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"exact": table})

    _assert_error(
        excinfo,
        kind="invalid_exact_table_header_cell",
        carrier_role="exact_table",
        frame_ordinal=0,
        frame_name="exact",
        row_ordinal=0,
        column_ordinal=1,
    )


def test_late_exact_table_data_cell_rejects_without_mutation() -> None:
    rejected = object()
    table = _exact_table(data=((1, "a"), (2, "b"), (3, rejected)))
    header_before = table.header_grid
    data_before = table.data
    frames = {"exact": table}

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames(frames)

    _assert_error(
        excinfo,
        kind="unsupported_scalar_carrier",
        carrier_role="exact_table",
        frame_ordinal=0,
        frame_name="exact",
        row_ordinal=2,
        column_ordinal=1,
    )
    assert frames["exact"] is table
    assert table.header_grid is header_before
    assert table.data is data_before
    assert table.data[2][1] is rejected


def test_exact_table_subclass_is_not_authorized_by_shape_or_ancestry() -> None:
    class _ExactTableSubclass(ExactTable):
        pass

    table = _ExactTableSubclass(
        header_grid=(("value",),),
        data=((1,),),
        header_rows=1,
        n_cols=1,
    )

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"exact": table})

    assert excinfo.value.kind == "unsupported_top_level_carrier"


def test_complete_e2_cell_rejection_path_does_not_invoke_hostile_protocols() -> None:
    calls: list[str] = []

    class _ProtocolBomb:
        def __getattribute__(self, name: str) -> object:
            if name == "__class__":  # pragma: no cover - must never run
                calls.append("class")
                raise AssertionError("instance __class__ lookup must not run")
            return object.__getattribute__(self, name)

        def __repr__(self) -> str:  # pragma: no cover - must never run
            calls.append("repr")
            raise AssertionError("repr must not run")

        def __str__(self) -> str:  # pragma: no cover - must never run
            calls.append("str")
            raise AssertionError("str must not run")

        def __eq__(self, other: object) -> bool:  # pragma: no cover - must never run
            calls.append("eq")
            raise AssertionError("equality must not run")

        def __hash__(self) -> int:  # pragma: no cover - must never run
            calls.append("hash")
            raise AssertionError("hashing must not run")

        def __iter__(self):  # pragma: no cover - must never run
            calls.append("iter")
            raise AssertionError("iteration must not run")

        def __array__(self, dtype=None, copy=None):  # pragma: no cover - must never run
            calls.append("array")
            raise AssertionError("NumPy conversion must not run")

    bomb = _ProtocolBomb()
    values = np.empty((2, 2), dtype=object)
    values[:] = [[1, 2], [3, None]]
    values[1, 1] = bomb
    frame = pd.DataFrame(values, columns=["a", "b"])
    calls.clear()

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames({"safe-name": frame})

    _assert_error(
        excinfo,
        kind="unsupported_scalar_carrier",
        carrier_role="dataframe",
        frame_ordinal=0,
        frame_name="safe-name",
        row_ordinal=1,
        column_ordinal=1,
    )
    assert "unsupported_scalar_carrier" in str(excinfo.value)
    assert calls == []


@pytest.mark.parametrize(
    "frames",
    [[], {}, {1: pd.DataFrame({"a": [1]})}, _FramesSubclass()],
)
def test_frames_requires_exact_dict_and_exact_string_names(frames: object) -> None:
    if type(frames) is dict and not frames:
        assert admit_ordinary_frames(frames) is frames
        return

    with pytest.raises(OrdinaryStructureAdmissionError) as excinfo:
        admit_ordinary_frames(frames)  # type: ignore[arg-type]

    expected = "invalid_frames_mapping" if type(frames) is not dict else "invalid_frame_name"
    assert excinfo.value.kind == expected


def test_empty_exact_string_frame_name_is_not_narrowed_by_e2() -> None:
    frame = pd.DataFrame({"value": [1]})

    assert admit_ordinary_frames({"": frame})[""] is frame


def test_reserved_meta_root_is_recognized_without_e3_validation() -> None:
    metadata = {"cyclic": None}
    metadata["cyclic"] = metadata
    frames = {"_meta": metadata, "data": pd.DataFrame({"value": [1]})}

    assert admit_ordinary_frames(frames) is frames
    assert frames["_meta"] is metadata
    assert metadata["cyclic"] is metadata
