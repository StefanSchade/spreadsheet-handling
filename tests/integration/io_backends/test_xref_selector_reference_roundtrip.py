"""Cross-carrier roundtrip for the XRef durable selector-reference contract.

FTR-XREF-PHYSICAL-LABEL-METADATA-AUTHORITY-P4A section 9.H reproduces section
8.1's decisive evidence for an *accepted* exact-str ``row_keys`` selector:
persist through JSON-directory, XLSX, and ODS, reload, and confirm the
physical column label, the persisted ``row_keys`` entry, and a later
``expand_xref`` rediscovery/lookup all agree. Section 8.1's own cross-carrier
probe showed the previously published *numeric* selector example does not
survive this same round trip on three of four carriers (the physical column
label silently retypes on reload); that example is retired by this FTR, not
pinned here -- only the accepted ``str`` selector is exercised.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.xref_crosstable import (
    contract_xref,
    expand_xref,
)
from spreadsheet_handling.io_backends.json_backend import JSONBackend
from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend

pytestmark = pytest.mark.ftr("FTR-XREF-PHYSICAL-LABEL-METADATA-AUTHORITY-P4A")

_CONFIG_ID = "region_matrix"


def _relation() -> pd.DataFrame:
    return pd.DataFrame([
        {"region": "north", "column_key": "q1", "value": "10"},
        {"region": "south", "column_key": "q1", "value": "20"},
    ])


def _contracted() -> dict[str, object]:
    return contract_xref(
        {"relation": _relation()},
        relation="relation",
        output="matrix",
        row_keys=["region"],
        name=_CONFIG_ID,
    )


def _assert_selector_survived_roundtrip(read_frames: dict[str, object]) -> None:
    matrix = read_frames["matrix"]
    # The physical column label itself reloaded as the identical exact str.
    assert "region" in list(matrix.columns)
    assert any(type(col) is str and col == "region" for col in matrix.columns)

    # The persisted row_keys metadata entry reloaded as the identical exact str.
    persisted_row_keys = read_frames["_meta"]["xref_crosstable"][_CONFIG_ID]["row_keys"]
    assert persisted_row_keys == ["region"]
    assert all(type(key) is str for key in persisted_row_keys)

    # A later XRef lookup/rediscovery still resolves the same physical column
    # by the same exact string reference and reproduces the original relation.
    expanded = expand_xref(
        read_frames, matrix="matrix", output="relation_back", row_keys="region"
    )
    got = (
        expanded["relation_back"][["region", "column_key", "value"]]
        .sort_values("region")
        .reset_index(drop=True)
    )
    expected = _relation().sort_values("region").reset_index(drop=True)
    pd.testing.assert_frame_equal(got, expected, check_dtype=False)


def test_json_directory_carrier_preserves_accepted_str_row_key_selector(
    tmp_path: Path,
) -> None:
    persisted = _contracted()
    out_dir = tmp_path / "selector_json"
    JSONBackend().write_multi(persisted, str(out_dir))

    read_frames = JSONBackend().read_multi(str(out_dir), header_levels=1)

    _assert_selector_survived_roundtrip(read_frames)


@pytest.mark.parametrize(
    "backend_factory, suffix",
    [
        (ExcelBackend, "xlsx"),
        (OdsBackend, "ods"),
    ],
)
def test_spreadsheet_carrier_preserves_accepted_str_row_key_selector(
    backend_factory, suffix, tmp_path: Path
) -> None:
    persisted = _contracted()
    path = tmp_path / f"selector.{suffix}"
    backend_factory().write_multi(persisted, str(path))

    read_frames = backend_factory().read_multi(str(path), header_levels=1)

    _assert_selector_survived_roundtrip(read_frames)
