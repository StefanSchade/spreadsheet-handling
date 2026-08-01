"""GX-3b end-to-end: GroupedMatrix -> XLSX -> exact table -> GroupedMatrix.

GX-3b of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. The forward composer projects a
``GroupedMatrix`` into an exact XLSX header grid; reading it back with the GX-3a
opt-in gate yields an ``ExactTable`` that ``reconstruct_grouped_matrix`` turns
back into a ``GroupedMatrix``; unchanged ``expand_grouped_xref`` then restores the
canonical relation. Without the opt-in gate the read is legacy (a DataFrame).
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
from spreadsheet_handling.io_backends.spreadsheet_contract import (
    build_spreadsheet_render_plan,
)
from spreadsheet_handling.io_backends.xlsx.openpyxl_parser import parse_workbook
from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook
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


def _write_grouped_xlsx(path: Path) -> None:
    gm = contract_grouped_xref(
        {"rel": _relation(), "src": _source()},
        relation="rel",
        output="Matrix",
        row_keys=["row_id"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )["Matrix"]
    plan = build_spreadsheet_render_plan({"Matrix": gm}, {})
    render_workbook(plan, path)


def _sorted(relation: pd.DataFrame) -> pd.DataFrame:
    return relation.sort_values(["row_id", "column_key"]).reset_index(drop=True)


def test_grouped_matrix_xlsx_roundtrip_to_grouped_matrix_and_relation(tmp_path):
    path = tmp_path / "grouped.xlsx"
    _write_grouped_xlsx(path)

    ir = parse_workbook(path, exact_header_depths={"Matrix": 2})
    frames = workbookir_to_frames(ir)
    assert isinstance(frames["Matrix"], ExactTable)

    frames["src"] = _source()
    reconstructed = reconstruct_grouped_matrix(
        frames,
        table="Matrix",
        output="mtx",
        row_keys=["row_id"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    restored = expand_grouped_xref(
        {"mtx": reconstructed["mtx"], "src": _source()},
        matrix="mtx",
        output="rel_out",
        row_keys=["row_id"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    pd.testing.assert_frame_equal(_sorted(restored["rel_out"]), _sorted(_relation()))


def test_reconstruct_then_expand_through_public_build_and_run():
    from spreadsheet_handling.pipeline.build import build_steps_from_config
    from spreadsheet_handling.pipeline.execution import run_pipeline

    exact = ExactTable(
        header_grid=(
            ("", "Kredit", "Kredit", "Einlage"),
            ("row_id", "Annuitaet", "Festzins", "Guthaben"),
        ),
        data=tuple(
            (rid, f"{rid}:{_KEYS[0]}", f"{rid}:{_KEYS[1]}", f"{rid}:{_KEYS[2]}")
            for rid in ("r1", "r2")
        ),
        header_rows=2,
        n_cols=4,
    )
    steps = build_steps_from_config(
        [
            {
                "step": "reconstruct_grouped_matrix",
                "table": "Matrix",
                "output": "mtx",
                "row_keys": ["row_id"],
                "source_frame": "src",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
            },
            {
                "step": "expand_grouped_xref",
                "matrix": "mtx",
                "output": "rel_out",
                "row_keys": ["row_id"],
                "source_frame": "src",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
            },
        ]
    )
    out = run_pipeline({"Matrix": exact, "src": _source()}, steps)
    pd.testing.assert_frame_equal(_sorted(out["rel_out"]), _sorted(_relation()))


def test_legacy_gate_stays_opt_in_without_exact_header_depths(tmp_path):
    path = tmp_path / "grouped.xlsx"
    _write_grouped_xlsx(path)

    # No exact_header_depths: legacy projection yields a DataFrame, not ExactTable.
    frames = workbookir_to_frames(parse_workbook(path))
    assert not isinstance(frames["Matrix"], ExactTable)
    assert isinstance(frames["Matrix"], pd.DataFrame)
