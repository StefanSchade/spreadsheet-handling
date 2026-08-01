"""GX-4 ODS configured-depth exact-header read (mirrors the GX-3a XLSX path).

FTR-XREF-AXIS-MAPPINGS-P4A2 GX-4. These tests pin the ODS adapter's opt-in
exact read: a configured per-sheet depth overrides merge-based inference and a
lossless per-cell ``header_grid`` is captured (merged masters resolved, blanks
kept, no ``" / "`` join). Fixtures are built directly from ``odf`` elements so
they exercise the ODS grid parser and interpretation, not the project's own
renderer only.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from odf.table import CoveredTableCell, Table, TableCell, TableRow
from odf.text import P

from spreadsheet_handling.core.exact_table import ExactTable
from spreadsheet_handling.io_backends.ods.odf_parser import _parse_table_grid, parse_workbook
from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.io_backends.ods.parser_interpretation import build_visible_sheet_ir
from spreadsheet_handling.io_backends.spreadsheet_contract import (
    build_spreadsheet_render_plan,
)
from spreadsheet_handling.io_backends.ods.odf_renderer import render_workbook
from spreadsheet_handling.domain.transformations.grouped_xref import contract_grouped_xref
from spreadsheet_handling.rendering.ir import WorkbookIR
from spreadsheet_handling.rendering.workbook_projection import workbookir_to_frames

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")


def _row(cells: list[object]) -> TableRow:
    """Build a table row. ``None`` is an empty cell; a ``("span", n, text)``
    triple is a horizontally spanned master followed by ``n - 1`` covered cells.
    """
    row = TableRow()
    for cell in cells:
        if isinstance(cell, tuple) and cell and cell[0] == "span":
            _, span, text = cell
            master = TableCell(numbercolumnsspanned=span)
            master.addElement(P(text=str(text)))
            row.addElement(master)
            for _ in range(span - 1):
                row.addElement(CoveredTableCell())
        elif cell is None or cell == "":
            row.addElement(TableCell())
        else:
            tc = TableCell()
            tc.addElement(P(text=str(cell)))
            row.addElement(tc)
    return row


def _table(name: str, rows: list[list[object]]) -> Table:
    table = Table(name=name)
    for r in rows:
        table.addElement(_row(r))
    return table


def _exact_table(name: str, rows: list[list[object]], depth: int) -> ExactTable:
    parsed = _parse_table_grid(_table(name, rows))
    sheet = build_visible_sheet_ir(
        parsed,
        sheet_name=name,
        meta_hints={},
        validations=[],
        autofilter_ref=None,
        exact_header_depth=depth,
    )
    ir = WorkbookIR()
    ir.sheets[name] = sheet
    frames = workbookir_to_frames(ir)
    return frames[name]


def test_exact_read_repeated_unmerged_labels_arity2() -> None:
    # The project's own writer emits repeated literal upper labels (no merges).
    et = _exact_table(
        "M",
        [
            ["", "Kredit", "Kredit", "Einlage"],
            ["row_id", "Ann", "Fest", "Gut"],
            ["r1", "x", "y", "z"],
        ],
        depth=2,
    )
    assert isinstance(et, ExactTable)
    assert et.header_rows == 2
    assert et.n_cols == 4
    assert et.header_grid == (
        ("", "Kredit", "Kredit", "Einlage"),
        ("row_id", "Ann", "Fest", "Gut"),
    )
    assert et.data == (("r1", "x", "y", "z"),)


def test_exact_read_merged_spanned_upper_labels_resolve_to_master() -> None:
    # A manually merged "Kredit" spanning columns 2-3 must read back identically
    # to the repeated-literal form (merged master resolved into every position).
    et = _exact_table(
        "M",
        [
            ["", ("span", 2, "Kredit"), "Einlage"],
            ["row_id", "Ann", "Fest", "Gut"],
            ["r1", "x", "y", "z"],
        ],
        depth=2,
    )
    assert et.header_grid == (
        ("", "Kredit", "Kredit", "Einlage"),
        ("row_id", "Ann", "Fest", "Gut"),
    )


def test_exact_read_arity3_merged_and_repeated() -> None:
    et = _exact_table(
        "M",
        [
            ["", ("span", 2, "C"), "D"],
            ["", "A", "A", "B"],
            ["row_id", "x", "y", "z"],
            ["r1", "1", "2", "3"],
        ],
        depth=3,
    )
    assert et.header_rows == 3
    assert et.header_grid == (
        ("", "C", "C", "D"),
        ("", "A", "A", "B"),
        ("row_id", "x", "y", "z"),
    )
    assert et.data == (("r1", "1", "2", "3"),)


def test_exact_read_blank_upper_rowkey_cells_preserved() -> None:
    # The row-key column's upper cells stay blank; they are not filled.
    et = _exact_table(
        "M",
        [
            ["", "Kredit", "Kredit"],
            ["row_id", "Ann", "Fest"],
            ["r1", "x", "y"],
        ],
        depth=2,
    )
    assert et.header_grid[0][0] == ""
    assert et.header_grid[1][0] == "row_id"


def test_exact_read_literal_slash_component_is_verbatim() -> None:
    # A literal " / " inside a label component must survive: no split, no join.
    et = _exact_table(
        "M",
        [
            ["", "A / B"],
            ["row_id", "C"],
            ["r1", "v"],
        ],
        depth=2,
    )
    assert et.header_grid == (("", "A / B"), ("row_id", "C"))


def test_configured_depth_overrides_merge_inference() -> None:
    # Physical grid with no merges: legacy inference detects a single header row,
    # but the configured depth of 2 reads two header rows in exact mode.
    rows = [
        ["", "Kredit", "Kredit"],
        ["row_id", "Ann", "Fest"],
        ["r1", "x", "y"],
    ]
    legacy = build_visible_sheet_ir(
        _parse_table_grid(_table("M", rows)),
        sheet_name="M",
        meta_hints={},
        validations=[],
        autofilter_ref=None,
    )
    assert legacy.tables[0].header_rows == 1
    assert legacy.tables[0].header_grid is None

    et = _exact_table("M", rows, depth=2)
    assert et.header_rows == 2


@pytest.mark.parametrize("bad", [0, -1, "2", 2.0, None])
def test_malformed_exact_header_depth_rejected(tmp_path: Path, bad: object) -> None:
    path = tmp_path / "m.ods"
    render_workbook(
        build_spreadsheet_render_plan({"M": pd.DataFrame({"a": [1]})}, {}), path
    )
    with pytest.raises(ValueError, match="positive integers"):
        parse_workbook(path, exact_header_depths={"M": bad})


def test_absent_exact_header_depths_is_legacy_noop(tmp_path: Path) -> None:
    path = tmp_path / "m.ods"
    render_workbook(
        build_spreadsheet_render_plan({"M": pd.DataFrame({"a": [1]})}, {}), path
    )
    # An empty/None mapping is a no-op (byte-identical legacy read).
    assert parse_workbook(path, exact_header_depths=None).sheets["M"].tables[0].header_grid is None
    assert parse_workbook(path, exact_header_depths={}).sheets["M"].tables[0].header_grid is None


def test_legacy_ods_read_unchanged_without_gate(tmp_path: Path) -> None:
    keys = ("credit.a", "credit.b", "deposit.c")
    rel = pd.DataFrame(
        [{"row_id": r, "column_key": k, "value": f"{r}:{k}"}
         for r in ("r1", "r2") for k in keys]
    )
    src = pd.DataFrame(
        {"key": list(keys), "grp": ["Kredit", "Kredit", "Einlage"],
         "leaf": ["Ann", "Fest", "Gut"]}
    )
    gm = contract_grouped_xref(
        {"rel": rel, "src": src}, relation="rel", output="Matrix",
        row_keys=["row_id"], source_frame="src", key_column="key",
        label_columns=["grp", "leaf"],
    )["Matrix"]
    path = tmp_path / "g.ods"
    render_workbook(build_spreadsheet_render_plan({"Matrix": gm}, {}), path)

    frames = workbookir_to_frames(parse_workbook(path))
    assert not isinstance(frames["Matrix"], ExactTable)
    assert isinstance(frames["Matrix"], pd.DataFrame)


def test_backend_option_exact_header_depths_seam(tmp_path: Path) -> None:
    keys = ("credit.a", "credit.b", "deposit.c")
    rel = pd.DataFrame(
        [{"row_id": r, "column_key": k, "value": f"{r}:{k}"}
         for r in ("r1",) for k in keys]
    )
    src = pd.DataFrame(
        {"key": list(keys), "grp": ["Kredit", "Kredit", "Einlage"],
         "leaf": ["Ann", "Fest", "Gut"]}
    )
    gm = contract_grouped_xref(
        {"rel": rel, "src": src}, relation="rel", output="Matrix",
        row_keys=["row_id"], source_frame="src", key_column="key",
        label_columns=["grp", "leaf"],
    )["Matrix"]
    path = tmp_path / "g.ods"
    render_workbook(build_spreadsheet_render_plan({"Matrix": gm}, {}), path)

    # No options -> legacy DataFrame.
    plain = OdsBackend().read_multi(str(path), header_levels=1)
    assert not isinstance(plain["Matrix"], ExactTable)

    # options.extra opt-in -> ExactTable.
    exact = OdsBackend().read_multi(
        str(path), header_levels=1,
        options={"extra": {"exact_header_depths": {"Matrix": 2}}},
    )
    assert isinstance(exact["Matrix"], ExactTable)
