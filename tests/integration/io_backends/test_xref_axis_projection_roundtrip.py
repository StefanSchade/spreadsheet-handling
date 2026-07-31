"""XLSX/ODS roundtrip integration for flat one-level axis-label projection.

Proves that projecting canonical axis keys to visible labels, contracting to a
matrix, persisting and re-reading the matrix across both carriers, expanding,
and restoring keys reproduces the canonical axis vocabulary exactly -- with no
change to XRef or the spreadsheet carriers (flat string headers only).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from spreadsheet_handling.domain.transformations.xref_axis_projection import (
    project_axis_labels,
    restore_axis_keys,
)
from spreadsheet_handling.domain.transformations.xref_crosstable import (
    contract_xref,
    expand_xref,
)

pytestmark = [
    pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2"),
]


def _source_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"char_id": "CHAR-0002", "char_name": "Galli"},
            {"char_id": "CHAR-0007", "char_name": "Trixi"},
        ]
    )


def _canonical_relation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"story_id": "S1", "column_key": "CHAR-0002", "value": "x"},
            {"story_id": "S1", "column_key": "CHAR-0007", "value": "y"},
            {"story_id": "S2", "column_key": "CHAR-0002", "value": "z"},
        ]
    )


def _contract_to_labelled_matrix() -> dict[str, object]:
    frames = {"chars": _source_frame(), "rel": _canonical_relation()}
    labelled = project_axis_labels(
        frames,
        relation="rel",
        output="rel_lbl",
        source_frame="chars",
        key_column="char_id",
        label_column="char_name",
    )
    matrix = contract_xref(
        labelled, relation="rel_lbl", output="matrix", row_keys="story_id"
    )
    # Persist only the readable matrix; the mapping source travels in-process.
    return {"matrix": matrix["matrix"]}


def _restore_from_read_matrix(read_frames: dict[str, object]) -> pd.DataFrame:
    expanded = expand_xref(
        read_frames,
        matrix="matrix",
        output="rel_lbl",
        row_keys="story_id",
        drop_empty=True,
    )
    restored = restore_axis_keys(
        {**expanded, "chars": _source_frame()},
        relation="rel_lbl",
        output="rel_back",
        source_frame="chars",
        key_column="char_id",
        label_column="char_name",
    )
    got = restored["rel_back"][["story_id", "column_key", "value"]]
    return got.sort_values(["story_id", "column_key"]).reset_index(drop=True)


def _expected_canonical() -> pd.DataFrame:
    return (
        _canonical_relation()
        .sort_values(["story_id", "column_key"])
        .reset_index(drop=True)
    )


@pytest.mark.parametrize(
    "backend_factory, suffix",
    [
        (ExcelBackend, "xlsx"),
        (OdsBackend, "ods"),
    ],
)
def test_flat_axis_projection_roundtrips_through_carrier(
    backend_factory, suffix, tmp_path: Path
) -> None:
    persisted = _contract_to_labelled_matrix()
    # Visible matrix headers are ordinary flat strings.
    assert set(persisted["matrix"].columns) == {"story_id", "Galli", "Trixi"}

    path = tmp_path / f"axis_projection.{suffix}"
    backend_factory().write_multi(persisted, str(path))
    read_frames = backend_factory().read_multi(str(path), header_levels=1)

    # Headers survived as flat strings (no MultiIndex / grouped headers).
    assert not isinstance(read_frames["matrix"].columns, pd.MultiIndex)
    assert set(read_frames["matrix"].columns) == {"story_id", "Galli", "Trixi"}

    got = _restore_from_read_matrix(read_frames)
    pd.testing.assert_frame_equal(got, _expected_canonical(), check_dtype=False)


def test_xlsx_and_ods_restore_identically(tmp_path: Path) -> None:
    persisted = _contract_to_labelled_matrix()

    xlsx_path = tmp_path / "axis.xlsx"
    ods_path = tmp_path / "axis.ods"
    ExcelBackend().write_multi(persisted, str(xlsx_path))
    OdsBackend().write_multi(persisted, str(ods_path))

    xlsx_back = ExcelBackend().read_multi(str(xlsx_path), header_levels=1)
    ods_back = OdsBackend().read_multi(str(ods_path), header_levels=1)

    xlsx_restored = _restore_from_read_matrix(xlsx_back)
    ods_restored = _restore_from_read_matrix(ods_back)

    pd.testing.assert_frame_equal(xlsx_restored, ods_restored, check_dtype=False)
    pd.testing.assert_frame_equal(
        xlsx_restored, _expected_canonical(), check_dtype=False
    )
