from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.io_backends import make_backend
from spreadsheet_handling.io_backends.ods.odf_parser import parse_workbook
from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend


pytestmark = pytest.mark.ftr("FTR-ODS-CALC-ADAPTER-IMPLEMENTATION-P3J")


def _sample_frames() -> dict[str, object]:
    return {
        "Products": pd.DataFrame(
            [
                {"id": "P-001", "status": "new", "_helper": "A"},
                {"id": "P-002", "status": "done", "_helper": "B"},
            ]
        ),
        "_meta": {
            "version": "3.4",
            "author": "ods-adapter",
            "auto_filter": True,
            "freeze_header": True,
            "helper_prefix": "_",
            "constraints": [
                {
                    "sheet": "Products",
                    "column": "status",
                    "rule": {"type": "in_list", "values": ["new", "done", "archived"]},
                }
            ],
        },
    }


def test_make_backend_returns_ods_backend() -> None:
    backend = make_backend("ods")
    assert isinstance(backend, OdsBackend)


def test_ods_backend_roundtrips_visible_frames_and_meta(tmp_path: Path) -> None:
    out = tmp_path / "products.ods"

    OdsBackend().write_multi(_sample_frames(), str(out))
    back = OdsBackend().read_multi(str(out), header_levels=1)

    assert "_meta" in back
    assert back["_meta"] == _sample_frames()["_meta"]
    assert list(back["Products"].columns) == ["id", "status", "_helper"]
    assert back["Products"].iloc[0]["status"] == "new"
    assert "_meta" not in {name for name, frame in back.items() if isinstance(frame, pd.DataFrame)}


def test_ods_parser_recovers_named_ranges_validations_and_filter_hint(tmp_path: Path) -> None:
    out = tmp_path / "products.ods"

    OdsBackend().write_multi(_sample_frames(), str(out))
    ir = parse_workbook(out)

    sheet = ir.sheets["Products"]
    named_range_names = {named_range.name for named_range in sheet.named_ranges}
    assert "products_products_table" in named_range_names
    assert "products_products_header" in named_range_names
    assert "products_products_body" in named_range_names

    assert sheet.meta["__autofilter_ref"] == "A1:C3"
    assert len(sheet.validations) == 1
    validation = sheet.validations[0]
    assert validation.kind == "list"
    assert validation.area == (2, 2, 3, 2)
    assert "new" in validation.formula

    assert "_meta" in ir.hidden_sheets
    assert ir.hidden_sheets["_meta"].meta["_hidden"] is True
