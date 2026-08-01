"""GX-5 public configured grouped-XRef roundtrip through the router savers.

GX-5 of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. This exercises the four public gates the
slice widened, using the public configuration path (``build_steps_from_config`` +
``run_pipeline``) and the router-facing ``save_xlsx``/``save_ods`` and
``load_xlsx``/``load_ods`` seams -- never the composer directly:

    canonical relation + live axis source
    -> public contract_grouped_xref
    -> configure_workbook_view (renamed physical grouped sheet)
    -> router saver -> real XLSX/ODS file
    -> router loader with exact_header_depths[physical visible sheet]
    -> apply_workbook_view_sheet_mappings
    -> reconstruct_grouped_matrix
    -> expand_grouped_xref
    -> canonical relation

It proves untouched relation identity, that one edited spreadsheet value survives,
repeated upper labels, a literal ``" / "`` label component, the renamed physical
sheet, grouped-carrier passage through the public router savers, XLSX/ODS parity,
and pre-render failure atomicity. It does not repeat the GX-3b/GX-4 parser and
domain matrices.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd
import pytest

from spreadsheet_handling.core.exact_table import ExactTable
from spreadsheet_handling.domain.transformations.grouped_xref import GroupedMatrix
from spreadsheet_handling.io_backends.base import BackendOptions
from spreadsheet_handling.io_backends.ods.ods_backend import load_ods, save_ods
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import load_xlsx, save_xlsx
from spreadsheet_handling.pipeline import build_steps_from_config, run_pipeline

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")

_KEYS = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")
_MATRIX_FRAME = "Bilanz"
_VISIBLE_SHEET = "Grouped Bilanz Matrix"
_EDITED_VALUE = "r1:credit.annuity_loan EDITED"

_BACKENDS: dict[str, tuple[Callable[..., Any], Callable[..., Any], str]] = {
    "xlsx": (save_xlsx, load_xlsx, ".xlsx"),
    "ods": (save_ods, load_ods, ".ods"),
}


def _source() -> pd.DataFrame:
    # "Kredit" repeats across two keys (repeated upper labels); one leaf label
    # carries a literal " / " delimiter component.
    return pd.DataFrame(
        {
            "key": list(_KEYS),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuität / Tilgung", "Festzins", "Guthaben"],
        }
    )


def _relation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"row_id": rid, "column_key": key, "value": f"{rid}:{key}"}
            for rid in ("r1", "r2")
            for key in _KEYS
        ]
    )


def _expected_after_edit() -> pd.DataFrame:
    relation = _relation()
    relation.loc[
        (relation["row_id"] == "r1") & (relation["column_key"] == "credit.annuity_loan"),
        "value",
    ] = _EDITED_VALUE
    return relation


def _sorted(relation: pd.DataFrame) -> pd.DataFrame:
    return relation.sort_values(["row_id", "column_key"]).reset_index(drop=True)


def _forward_frames() -> dict[str, Any]:
    """Public config build/run: canonical relation -> grouped carrier + renamed view."""
    return run_pipeline(
        {"rel": _relation(), "src": _source(), "_meta": {}},
        build_steps_from_config(
            [
                {
                    "step": "contract_grouped_xref",
                    "relation": "rel",
                    "output": _MATRIX_FRAME,
                    "row_keys": ["row_id"],
                    "source_frame": "src",
                    "key_column": "key",
                    "label_columns": ["grp", "leaf"],
                },
                {
                    "step": "configure_workbook_view",
                    "sheets": [{"frame": _MATRIX_FRAME, "sheet": _VISIBLE_SHEET}],
                },
            ]
        ),
    )


def _with_edited_cell(exact: ExactTable, new_value: str) -> ExactTable:
    """Rebuild an ExactTable with the first dynamic data cell edited (r1 x key0)."""
    data = [list(row) for row in exact.data]
    data[0][1] = new_value
    return ExactTable(
        header_grid=exact.header_grid,
        data=tuple(tuple(row) for row in data),
        header_rows=exact.header_rows,
        n_cols=exact.n_cols,
    )


def _restore_from(reverse_frames: dict[str, Any]) -> pd.DataFrame:
    """Public reverse config: remap visible sheet -> reconstruct -> expand."""
    mapped = run_pipeline(
        reverse_frames,
        build_steps_from_config(
            [
                {
                    "step": "apply_workbook_view_sheet_mappings",
                    "logical_frames": [_MATRIX_FRAME],
                }
            ]
        ),
    )
    mapped["src"] = _source()
    restored = run_pipeline(
        mapped,
        build_steps_from_config(
            [
                {
                    "step": "reconstruct_grouped_matrix",
                    "table": _MATRIX_FRAME,
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
        ),
    )
    return restored["rel_out"]


def _load_options() -> BackendOptions:
    return BackendOptions(extra={"exact_header_depths": {_VISIBLE_SHEET: 2}})


@pytest.mark.parametrize("backend", ["xlsx", "ods"])
def test_gx5_public_configured_grouped_roundtrip(tmp_path: Path, backend: str) -> None:
    saver, loader, suffix = _BACKENDS[backend]

    forward = _forward_frames()
    # Public build produced the trusted grouped carrier; the view renamed its
    # physical sheet so the visible name differs from the logical frame.
    assert isinstance(forward[_MATRIX_FRAME], GroupedMatrix)
    assert forward["_meta"]["workbook_view"]["sheet_mappings"] == [
        {"sheet": _VISIBLE_SHEET, "frame": _MATRIX_FRAME}
    ]

    path = tmp_path / f"gx5-grouped{suffix}"
    # The grouped carrier passes through the public router saver unchanged.
    saver(forward, str(path))
    assert path.exists()

    reverse_frames = loader(str(path), options=_load_options())
    # Read back keyed by the renamed physical sheet, as an exact carrier.
    assert _VISIBLE_SHEET in reverse_frames
    assert _MATRIX_FRAME not in reverse_frames
    exact = reverse_frames[_VISIBLE_SHEET]
    assert isinstance(exact, ExactTable)

    # Repeated upper labels and a literal " / " leaf component survived the file.
    upper_row, leaf_row = exact.header_grid[0], exact.header_grid[1]
    assert upper_row.count("Kredit") == 2
    assert any(" / " in cell for cell in leaf_row)

    # Untouched relation identity.
    identity = _restore_from(reverse_frames)
    pd.testing.assert_frame_equal(
        _sorted(identity), _sorted(_relation()), check_dtype=False
    )

    # One edited spreadsheet-boundary value survives back to the canonical relation.
    edited_frames = loader(str(path), options=_load_options())
    edited_frames[_VISIBLE_SHEET] = _with_edited_cell(
        edited_frames[_VISIBLE_SHEET], _EDITED_VALUE
    )
    edited = _restore_from(edited_frames)
    pd.testing.assert_frame_equal(
        _sorted(edited), _sorted(_expected_after_edit()), check_dtype=False
    )


def test_gx5_xlsx_and_ods_roundtrips_are_semantically_equal(tmp_path: Path) -> None:
    forward = _forward_frames()

    restored: dict[str, pd.DataFrame] = {}
    for backend, (saver, loader, suffix) in _BACKENDS.items():
        path = tmp_path / f"gx5-parity{suffix}"
        saver(forward, str(path))
        restored[backend] = _sorted(_restore_from(loader(str(path), options=_load_options())))

    pd.testing.assert_frame_equal(restored["xlsx"], restored["ods"], check_dtype=False)
    pd.testing.assert_frame_equal(restored["xlsx"], _sorted(_relation()), check_dtype=False)


def test_gx5_pre_render_grouped_view_failure_is_atomic(tmp_path: Path) -> None:
    grouped = _forward_frames()[_MATRIX_FRAME]
    flat = pd.DataFrame({"id": [1]})
    # A duplicate visible sheet name in a grouped selection fails inside
    # select_render_frames, before any composition or file publication.
    meta = {
        "workbook_view": {
            "sheets": [
                {"frame": _MATRIX_FRAME, "sheet": "Dup"},
                {"frame": "flat", "sheet": "Dup"},
            ]
        }
    }
    frames = {_MATRIX_FRAME: grouped, "flat": flat, "_meta": meta}
    path = tmp_path / "should-not-exist.xlsx"

    with pytest.raises(ValueError, match="Duplicate workbook view sheet name"):
        save_xlsx(frames, str(path))

    # No target output file was created.
    assert not path.exists()
    # Caller Frames and _meta are unchanged (identity and content preserved).
    assert set(frames) == {_MATRIX_FRAME, "flat", "_meta"}
    assert frames[_MATRIX_FRAME] is grouped
    assert frames["flat"] is flat
    assert frames["_meta"] is meta
    assert meta == {
        "workbook_view": {
            "sheets": [
                {"frame": _MATRIX_FRAME, "sheet": "Dup"},
                {"frame": "flat", "sheet": "Dup"},
            ]
        }
    }
