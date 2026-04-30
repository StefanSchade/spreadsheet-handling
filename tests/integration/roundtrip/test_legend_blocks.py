"""Legend-block roundtrip integration slice.

Guards that rendered legend blocks survive XLSX and ODS roundtrips as metadata
rather than becoming ordinary data frames.
"""

from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.ods.odf_parser import parse_workbook as parse_ods_workbook
from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.io_backends.xlsx.openpyxl_parser import parse_workbook
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend

pytestmark = [
    pytest.mark.ftr("FTR-LEGEND-BLOCKS"),
    pytest.mark.ftr("FTR-TEST-NAMING-AND-CONVENTIONS-P3C"),
]


def _frames_with_legend() -> dict:
    meta = {
        "legend_blocks": {
            "status_codes": {
                "title": "Status Codes",
                "placement": {
                    "sheet": "product_matrix",
                    "anchor": "right_of_table",
                    "target": "product_matrix",
                },
                "entries": [
                    {"token": "E", "label": "Editable", "group": "input"},
                    {"token": "E-R-K", "label": "Capital-path recalculation", "group": "input"},
                    {"token": "x", "label": "Not meaningful", "group": "blocked"},
                ],
            }
        }
    }
    return {
        "product_matrix": pd.DataFrame(
            {
                "feature": ["currency", "amount"],
                "FZ-AD": ["E", "E-R-K"],
            }
        ),
        "_meta": meta,
    }


def test_xlsx_legend_block_roundtrips_as_metadata_not_data_frame(tmp_path):
    xlsx = tmp_path / "legend.xlsx"
    ExcelBackend().write_multi(_frames_with_legend(), str(xlsx))

    ir = parse_workbook(xlsx)
    sheet = ir.sheets["product_matrix"]

    assert len(sheet.tables) == 2
    assert sheet.tables[0].kind == "data"
    assert sheet.tables[0].headers == ["feature", "FZ-AD"]
    assert sheet.tables[1].kind == "legend"
    assert sheet.tables[1].headers == ["Token", "Meaning", "Group"]
    assert sheet.tables[1].data[1] == ["E-R-K", "Capital-path recalculation", "input"]

    back = ExcelBackend().read_multi(str(xlsx), header_levels=1)
    assert list(back["product_matrix"].columns) == ["feature", "FZ-AD"]
    assert back["product_matrix"].to_dict(orient="records") == [
        {"feature": "currency", "FZ-AD": "E"},
        {"feature": "amount", "FZ-AD": "E-R-K"},
    ]
    assert "legend_blocks" in back["_meta"]


def test_ods_legend_block_roundtrips_as_metadata_not_data_frame(tmp_path):
    ods = tmp_path / "legend.ods"
    OdsBackend().write_multi(_frames_with_legend(), str(ods))

    ir = parse_ods_workbook(ods)
    sheet = ir.sheets["product_matrix"]

    assert len(sheet.tables) == 2
    assert sheet.tables[0].kind == "data"
    assert sheet.tables[0].headers == ["feature", "FZ-AD"]
    assert sheet.tables[1].kind == "legend"
    assert sheet.tables[1].headers == ["Token", "Meaning", "Group"]
    assert sheet.tables[1].data[1] == ["E-R-K", "Capital-path recalculation", "input"]

    back = OdsBackend().read_multi(str(ods), header_levels=1)
    assert list(back["product_matrix"].columns) == ["feature", "FZ-AD"]
    assert back["product_matrix"].to_dict(orient="records") == [
        {"feature": "currency", "FZ-AD": "E"},
        {"feature": "amount", "FZ-AD": "E-R-K"},
    ]
    assert "legend_blocks" in back["_meta"]
