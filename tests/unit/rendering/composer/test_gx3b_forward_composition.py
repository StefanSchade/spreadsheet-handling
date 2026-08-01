"""GX-3b forward composition: a GroupedMatrix projects to an exact header grid.

GX-3b of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. ``compose_workbook`` recognises a
``GroupedMatrix`` Frames value and builds one exact-mode ``TableBlock`` (lossless
``header_grid``, repeated literal labels, no merges, canonical dynamic keys never
rendered), reusing the accepted GX-3a exact-write branch. Ordinary DataFrames are
unchanged.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.grouped_xref import (
    GroupedXrefError,
    contract_grouped_xref,
)
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.plan import MergeCells, SetHeader

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")


def _grouped_matrix(
    relation: pd.DataFrame,
    source: pd.DataFrame,
    *,
    row_keys,
    label_columns,
):
    out = contract_grouped_xref(
        {"rel": relation, "src": source},
        relation="rel",
        output="Matrix",
        row_keys=row_keys,
        source_frame="src",
        key_column="key",
        label_columns=label_columns,
    )
    return out["Matrix"]


def _arity2():
    keys = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")
    relation = pd.DataFrame(
        [
            {"row_id": rid, "column_key": k, "value": f"{rid}:{k}"}
            for rid in ("r1", "r2")
            for k in keys
        ]
    )
    source = pd.DataFrame(
        {
            "key": list(keys),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitaet", "Festzins", "Guthaben"],
        }
    )
    return relation, source


def test_arity2_grouped_matrix_projects_to_exact_header_grid():
    relation, source = _arity2()
    gm = _grouped_matrix(relation, source, row_keys=["row_id"], label_columns=["grp", "leaf"])

    ir = compose_workbook({"Matrix": gm}, meta={})
    tbl = ir.sheets["Matrix"].tables[0]

    assert tbl.header_grid == (
        ("", "Kredit", "Kredit", "Einlage"),
        ("row_id", "Annuitaet", "Festzins", "Guthaben"),
    )
    assert tbl.header_rows == gm.header.arity == 2
    assert tbl.n_cols == 4
    # authoritative grid; the legacy sheet-level grid is not seeded (one truth).
    assert "__header_grid" not in ir.sheets["Matrix"].meta


def test_arity3_grouped_matrix_projects_three_header_rows():
    keys = ("a.x", "a.y", "b.z")
    relation = pd.DataFrame(
        [{"row_id": "r1", "column_key": k, "value": k} for k in keys]
    )
    source = pd.DataFrame(
        {
            "key": list(keys),
            "l1": ["A", "A", "B"],
            "l2": ["A1", "A1", "B1"],
            "l3": ["x", "y", "z"],
        }
    )
    gm = _grouped_matrix(relation, source, row_keys=["row_id"], label_columns=["l1", "l2", "l3"])

    tbl = compose_workbook({"Matrix": gm}, meta={}).sheets["Matrix"].tables[0]
    assert tbl.header_rows == 3
    assert tbl.header_grid == (
        ("", "A", "A", "B"),
        ("", "A1", "A1", "B1"),
        ("row_id", "x", "y", "z"),
    )


def test_multiple_row_keys_show_leaf_label_and_blank_uppers():
    keys = ("a.x", "b.y")
    relation = pd.DataFrame(
        [
            {"r1": "p", "r2": "q", "column_key": k, "value": k}
            for k in keys
        ]
    )
    source = pd.DataFrame({"key": list(keys), "grp": ["A", "B"], "leaf": ["x", "y"]})
    gm = _grouped_matrix(relation, source, row_keys=["r1", "r2"], label_columns=["grp", "leaf"])

    tbl = compose_workbook({"Matrix": gm}, meta={}).sheets["Matrix"].tables[0]
    # two row-key columns first, both blank in the upper row, leaf labels below.
    assert tbl.header_grid[0][:2] == ("", "")
    assert tbl.header_grid[1][:2] == ("r1", "r2")


def test_repeated_upper_labels_are_written_as_repeated_literals():
    relation, source = _arity2()
    gm = _grouped_matrix(relation, source, row_keys=["row_id"], label_columns=["grp", "leaf"])
    tbl = compose_workbook({"Matrix": gm}, meta={}).sheets["Matrix"].tables[0]
    # "Kredit" repeats literally across the two credit columns (no merge).
    assert tbl.header_grid[0][1] == "Kredit"
    assert tbl.header_grid[0][2] == "Kredit"


def test_literal_delimiter_component_survives_verbatim():
    keys = ("a.x", "b.y")
    relation = pd.DataFrame([{"row_id": "r1", "column_key": k, "value": k} for k in keys])
    source = pd.DataFrame(
        {"key": list(keys), "grp": ["G / H", "Einlage"], "leaf": ["x", "y"]}
    )
    gm = _grouped_matrix(relation, source, row_keys=["row_id"], label_columns=["grp", "leaf"])
    tbl = compose_workbook({"Matrix": gm}, meta={}).sheets["Matrix"].tables[0]
    assert tbl.header_grid[0][1] == "G / H"


def test_canonical_dynamic_keys_are_not_rendered():
    relation, source = _arity2()
    gm = _grouped_matrix(relation, source, row_keys=["row_id"], label_columns=["grp", "leaf"])
    tbl = compose_workbook({"Matrix": gm}, meta={}).sheets["Matrix"].tables[0]
    flat_cells = {cell for row in tbl.header_grid for cell in row}
    assert "credit.annuity_loan" not in flat_cells
    assert not any("." in cell for cell in flat_cells if cell)


def test_data_block_placed_after_header_and_holds_frame_values():
    relation, source = _arity2()
    gm = _grouped_matrix(relation, source, row_keys=["row_id"], label_columns=["grp", "leaf"])
    tbl = compose_workbook({"Matrix": gm}, meta={}).sheets["Matrix"].tables[0]
    assert tbl.data == gm.frame.values.tolist()
    assert tbl.n_rows == tbl.header_rows + len(gm.frame)


def test_render_plan_emits_verbatim_headers_and_no_merges():
    relation, source = _arity2()
    gm = _grouped_matrix(relation, source, row_keys=["row_id"], label_columns=["grp", "leaf"])
    ir = compose_workbook({"Matrix": gm}, meta={})
    plan = build_render_plan(ir)
    header_texts = {op.text for op in plan.ops if isinstance(op, SetHeader)}
    assert "Kredit" in header_texts and "row_id" in header_texts
    assert not any(isinstance(op, MergeCells) for op in plan.ops)


def test_edited_carrier_data_cells_are_composed():
    relation, source = _arity2()
    gm = _grouped_matrix(relation, source, row_keys=["row_id"], label_columns=["grp", "leaf"])
    gm.frame.iloc[0, 1] = "EDITED"
    tbl = compose_workbook({"Matrix": gm}, meta={}).sheets["Matrix"].tables[0]
    assert tbl.data[0][1] == "EDITED"


def test_malformed_carrier_rejected_before_composition():
    relation, source = _arity2()
    gm = _grouped_matrix(relation, source, row_keys=["row_id"], label_columns=["grp", "leaf"])
    # Break the frame/header width pairing post-construction.
    gm.frame.drop(columns=[gm.frame.columns[-1]], inplace=True)
    with pytest.raises(GroupedXrefError):
        compose_workbook({"Matrix": gm}, meta={})


def test_ordinary_dataframe_unchanged_alongside_grouped_matrix():
    relation, source = _arity2()
    gm = _grouped_matrix(relation, source, row_keys=["row_id"], label_columns=["grp", "leaf"])
    ordinary = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    ir = compose_workbook({"Matrix": gm, "Plain": ordinary}, meta={})

    plain = ir.sheets["Plain"].tables[0]
    assert plain.header_grid is None
    assert plain.headers == ["x", "y"]
    assert ir.sheets["Plain"].meta["__header_grid"] == [["x", "y"]]
