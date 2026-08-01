"""GX-4 end-to-end: GroupedMatrix -> ODS -> exact table -> GroupedMatrix.

FTR-XREF-AXIS-MAPPINGS-P4A2 GX-4. The forward composer projects a
``GroupedMatrix`` into an exact ODS header grid; reading it back with the opt-in
depth gate yields an ``ExactTable`` that the unchanged ``reconstruct_grouped_matrix``
turns back into a ``GroupedMatrix``; unchanged ``expand_grouped_xref`` then
restores the canonical relation. This is the XLSX GX-3b flow over the ODS
adapter, reusing the same backend-neutral carrier and domain step.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.core.exact_table import ExactTable
from spreadsheet_handling.domain.transformations.grouped_xref import (
    contract_grouped_xref,
    expand_grouped_xref,
    reconstruct_grouped_matrix,
)
from spreadsheet_handling.io_backends.ods.odf_parser import parse_workbook
from spreadsheet_handling.io_backends.ods.odf_renderer import render_workbook
from spreadsheet_handling.io_backends.spreadsheet_contract import (
    build_spreadsheet_render_plan,
)
from spreadsheet_handling.rendering.workbook_projection import workbookir_to_frames

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")

_KEYS = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")


def _relation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"row_id": rid, "column_key": k, "value": f"{rid}:{k}"}
            for rid in ("r1", "r2")
            for k in _KEYS
        ]
    )


def _source() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "key": list(_KEYS),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitaet", "Festzins", "Guthaben"],
        }
    )


def _write_grouped_ods(path: Path, gm) -> None:
    render_workbook(build_spreadsheet_render_plan({"Matrix": gm}, {}), path)


def _sorted(relation: pd.DataFrame) -> pd.DataFrame:
    return relation.sort_values(["row_id", "column_key"]).reset_index(drop=True)


def _read_exact(path: Path, depth: int = 2) -> ExactTable:
    frames = workbookir_to_frames(parse_workbook(path, exact_header_depths={"Matrix": depth}))
    assert isinstance(frames["Matrix"], ExactTable)
    return frames["Matrix"]


def _reconstruct_and_expand(exact: ExactTable, label_columns, src) -> pd.DataFrame:
    rec = reconstruct_grouped_matrix(
        {"Matrix": exact, "src": src},
        table="Matrix", output="mtx", row_keys=["row_id"],
        source_frame="src", key_column="key", label_columns=list(label_columns),
    )
    restored = expand_grouped_xref(
        {"mtx": rec["mtx"], "src": src},
        matrix="mtx", output="rel_out", row_keys=["row_id"],
        source_frame="src", key_column="key", label_columns=list(label_columns),
    )
    return restored["rel_out"]


def test_ods_grouped_roundtrip_untouched(tmp_path):
    gm = contract_grouped_xref(
        {"rel": _relation(), "src": _source()}, relation="rel", output="Matrix",
        row_keys=["row_id"], source_frame="src", key_column="key",
        label_columns=["grp", "leaf"],
    )["Matrix"]
    path = tmp_path / "grouped.ods"
    _write_grouped_ods(path, gm)
    out = _reconstruct_and_expand(_read_exact(path), ["grp", "leaf"], _source())
    pd.testing.assert_frame_equal(_sorted(out), _sorted(_relation()))


def test_ods_grouped_roundtrip_edited_data(tmp_path):
    gm = contract_grouped_xref(
        {"rel": _relation(), "src": _source()}, relation="rel", output="Matrix",
        row_keys=["row_id"], source_frame="src", key_column="key",
        label_columns=["grp", "leaf"],
    )["Matrix"]
    path = tmp_path / "grouped.ods"
    _write_grouped_ods(path, gm)
    exact = _read_exact(path)
    rows = [list(r) for r in exact.data]
    rows[0][1] = "EDITED"
    edited = ExactTable(
        header_grid=exact.header_grid, data=tuple(tuple(r) for r in rows),
        header_rows=exact.header_rows, n_cols=exact.n_cols,
    )
    out = _reconstruct_and_expand(edited, ["grp", "leaf"], _source())
    val = out[(out.row_id == "r1") & (out.column_key == _KEYS[0])]["value"].iloc[0]
    assert val == "EDITED"


def test_ods_grouped_roundtrip_dynamic_reorder(tmp_path):
    gm = contract_grouped_xref(
        {"rel": _relation(), "src": _source()}, relation="rel", output="Matrix",
        row_keys=["row_id"], source_frame="src", key_column="key",
        label_columns=["grp", "leaf"],
    )["Matrix"]
    path = tmp_path / "grouped.ods"
    _write_grouped_ods(path, gm)
    exact = _read_exact(path)
    order = [0] + list(range(exact.n_cols - 1, 0, -1))  # keep row_id, reverse dynamics
    reordered = ExactTable(
        header_grid=tuple(tuple(row[i] for i in order) for row in exact.header_grid),
        data=tuple(tuple(row[i] for i in order) for row in exact.data),
        header_rows=exact.header_rows, n_cols=exact.n_cols,
    )
    out = _reconstruct_and_expand(reordered, ["grp", "leaf"], _source())
    pd.testing.assert_frame_equal(_sorted(out), _sorted(_relation()))


def test_ods_grouped_roundtrip_valid_deletion(tmp_path):
    gm = contract_grouped_xref(
        {"rel": _relation(), "src": _source()}, relation="rel", output="Matrix",
        row_keys=["row_id"], source_frame="src", key_column="key",
        label_columns=["grp", "leaf"],
    )["Matrix"]
    path = tmp_path / "grouped.ods"
    _write_grouped_ods(path, gm)
    exact = _read_exact(path)
    n = exact.n_cols - 1  # drop last dynamic column
    smaller = ExactTable(
        header_grid=tuple(tuple(row[:n]) for row in exact.header_grid),
        data=tuple(tuple(row[:n]) for row in exact.data),
        header_rows=exact.header_rows, n_cols=n,
    )
    out = _reconstruct_and_expand(smaller, ["grp", "leaf"], _source())
    assert _KEYS[-1] not in set(out.column_key.unique())
    assert set(out.column_key.unique()) == set(_KEYS[:-1])


def test_ods_grouped_roundtrip_arity3(tmp_path):
    keys = ("c.a.x", "c.a.y", "d.b.z")
    src = pd.DataFrame(
        {"key": list(keys), "l1": ["C", "C", "D"], "l2": ["A", "A", "B"],
         "l3": ["x", "y", "z"]}
    )
    rel = pd.DataFrame(
        [{"row_id": r, "column_key": k, "value": f"{r}:{k}"}
         for r in ("r1", "r2") for k in keys]
    )
    gm = contract_grouped_xref(
        {"rel": rel, "src": src}, relation="rel", output="Matrix",
        row_keys=["row_id"], source_frame="src", key_column="key",
        label_columns=["l1", "l2", "l3"],
    )["Matrix"]
    path = tmp_path / "grouped3.ods"
    _write_grouped_ods(path, gm)
    exact = _read_exact(path, depth=3)
    out = _reconstruct_and_expand(exact, ["l1", "l2", "l3"], src)
    pd.testing.assert_frame_equal(_sorted(out), _sorted(rel))
