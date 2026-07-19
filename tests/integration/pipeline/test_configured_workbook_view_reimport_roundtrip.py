"""Configured reference reimport roundtrip slice for
FTR-WORKBOOK-VIEW-ROUNDTRIP-RECOMPOSITION-P4A.

This proves that a configured pipeline can take an edited workbook view --
written under a *renamed* visible sheet -- back to canonical relation frames
using only existing machinery:

* existing forward ``contract_xref`` + ``configure_workbook_view``
* the Slice-A ``apply_workbook_view_sheet_mappings`` remap step
* existing ``expand_xref`` recomposition

No new matrix logic, no conflict detection, no precedence handling. Payload
conflict / precedence handling is intentionally out of scope here and is
deferred to FTR-WORKBOOK-VIEW-PAYLOAD-CONFLICT-PRECEDENCE-P6.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from spreadsheet_handling.pipeline import build_steps_from_config, run_pipeline


pytestmark = pytest.mark.ftr("FTR-WORKBOOK-VIEW-ROUNDTRIP-RECOMPOSITION-P4A")

_AXIS_COLUMNS = ["default", "product_a"]
_VISIBLE_SHEET = "Editable Resources"
_MATRIX_FRAME = "localized_matrix"
_CANONICAL_FRAME = "localized_values"


def _canonical_frames() -> dict[str, Any]:
    return {
        _CANONICAL_FRAME: pd.DataFrame(
            [
                {"resource_key": "r1", "context_id": "default", "text": "Alpha"},
                {"resource_key": "r1", "context_id": "product_a", "text": "Alpha A"},
                {"resource_key": "r2", "context_id": "default", "text": "Beta"},
                {"resource_key": "r2", "context_id": "product_a", "text": "Beta A"},
            ]
        ),
        "_meta": {},
    }


def _forward_pipeline() -> list[dict[str, Any]]:
    return [
        {
            "step": "contract_xref",
            "relation": _CANONICAL_FRAME,
            "output": _MATRIX_FRAME,
            "row_keys": ["resource_key"],
            "column_key": "context_id",
            "value": "text",
            "column_keys": _AXIS_COLUMNS,
            "name": "localized_contexts",
        },
        {
            "step": "configure_workbook_view",
            "sheets": [{"frame": _MATRIX_FRAME, "sheet": _VISIBLE_SHEET}],
        },
    ]


def _reverse_pipeline() -> list[dict[str, Any]]:
    return [
        {
            "step": "apply_workbook_view_sheet_mappings",
            "logical_frames": [_MATRIX_FRAME, _CANONICAL_FRAME],
        },
        {
            "step": "expand_xref",
            "matrix": _MATRIX_FRAME,
            "output": _CANONICAL_FRAME,
            "row_keys": ["resource_key"],
            "value_columns": _AXIS_COLUMNS,
            "column_key": "context_id",
            "value": "text",
            "drop_empty": False,
            "name": "localized_contexts",
        },
    ]


def _spreadsheet_roundtrips(
    tmp_path: Path,
    frames: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    xlsx_path = tmp_path / "configured-reimport.xlsx"
    ods_path = tmp_path / "configured-reimport.ods"

    ExcelBackend().write_multi(frames, str(xlsx_path))
    OdsBackend().write_multi(frames, str(ods_path))

    return {
        "xlsx": ExcelBackend().read_multi(str(xlsx_path), header_levels=1),
        "ods": OdsBackend().read_multi(str(ods_path), header_levels=1),
    }


def _expected_after_edit() -> pd.DataFrame:
    expected = _canonical_frames()[_CANONICAL_FRAME].copy()
    expected.loc[
        (expected["resource_key"] == "r1")
        & (expected["context_id"] == "product_a"),
        "text",
    ] = "Alpha A EDITED"
    return expected


def _ordered(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        ["resource_key", "context_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def test_configured_reimport_roundtrip_across_xlsx_and_ods(tmp_path: Path) -> None:
    forward = run_pipeline(
        _canonical_frames(),
        build_steps_from_config(_forward_pipeline()),
    )

    # Forward produced the matrix view frame; the workbook view renames its
    # visible sheet so the physical sheet name differs from the logical frame.
    assert list(forward[_MATRIX_FRAME].columns) == ["resource_key", *_AXIS_COLUMNS]
    assert forward["_meta"]["workbook_view"]["sheet_mappings"] == [
        {
            "sheet": _VISIBLE_SHEET,
            "frame": _MATRIX_FRAME,
        }
    ]

    for backend_name, workbook_frames in _spreadsheet_roundtrips(
        tmp_path, forward
    ).items():
        # Read back keyed by the *renamed physical sheet*, not the frame name.
        assert _VISIBLE_SHEET in workbook_frames, backend_name
        assert _MATRIX_FRAME not in workbook_frames, backend_name

        # Simulate a business edit on one matrix cell of the renamed sheet.
        edited = workbook_frames[_VISIBLE_SHEET]
        edited.loc[edited["resource_key"] == "r1", "product_a"] = "Alpha A EDITED"

        steps = build_steps_from_config(_reverse_pipeline())
        recomposed = run_pipeline(workbook_frames, steps)

        # The remap step re-keyed the visible sheet to the logical frame.
        assert _VISIBLE_SHEET not in recomposed, backend_name
        assert _MATRIX_FRAME in recomposed, backend_name

        # Existing expand_xref produced canonical relation rows; the edited
        # value is reflected and unchanged values roundtrip identically.
        pd.testing.assert_frame_equal(
            _ordered(recomposed[_CANONICAL_FRAME]),
            _ordered(_expected_after_edit()),
            check_dtype=False,
            obj=f"{backend_name} recomposed canonical relation",
        )


def test_configured_reimport_roundtrip_is_identity_without_edits(
    tmp_path: Path,
) -> None:
    forward = run_pipeline(
        _canonical_frames(),
        build_steps_from_config(_forward_pipeline()),
    )

    for backend_name, workbook_frames in _spreadsheet_roundtrips(
        tmp_path, forward
    ).items():
        recomposed = run_pipeline(
            workbook_frames,
            build_steps_from_config(_reverse_pipeline()),
        )

        pd.testing.assert_frame_equal(
            _ordered(recomposed[_CANONICAL_FRAME]),
            _ordered(_canonical_frames()[_CANONICAL_FRAME]),
            check_dtype=False,
            obj=f"{backend_name} unchanged matrix roundtrip",
        )
