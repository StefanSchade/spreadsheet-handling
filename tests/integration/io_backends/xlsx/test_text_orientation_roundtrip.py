from __future__ import annotations

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment

from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend


pytestmark = pytest.mark.ftr("FTR-TEXT-ORIENTATION-ROUNDTRIP-P5")


def _write_source_workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws["A1"] = "Category"
    ws["B1"] = "Value"
    ws["A2"] = "alpha"
    ws["B2"] = 1
    ws["A1"].alignment = Alignment(text_rotation=90)
    ws["B1"].alignment = Alignment(text_rotation=45)
    wb.save(path)
    wb.close()


def _text_orientations(frames, sheet_name="Data"):
    return frames["_meta"]["sheets"][sheet_name]["text_orientations"]


def test_xlsx_text_orientations_are_parsed_into_sheet_metadata(tmp_path):
    source = tmp_path / "source_rotation.xlsx"
    _write_source_workbook(source)

    frames = ExcelBackend().read_multi(str(source), header_levels=1)

    orients = _text_orientations(frames)
    assert orients["A1"] == {"rotation": 90, "source": "workbook"}
    assert orients["B1"] == {"rotation": 45, "source": "workbook"}


def test_xlsx_renderer_applies_text_orientation_metadata(tmp_path):
    frames = {
        "Data": pd.DataFrame({"Category": ["alpha"], "Value": [1]}),
        "_meta": {
            "sheets": {
                "Data": {
                    "text_orientations": {
                        "A1": {"rotation": 90, "source": "workbook"},
                        "B1": {"rotation": 45, "source": "workbook"},
                    }
                }
            }
        },
    }
    out = tmp_path / "rendered_rotation.xlsx"

    ExcelBackend().write_multi(frames, str(out))

    wb = load_workbook(out)
    try:
        ws = wb["Data"]
        assert ws["A1"].alignment.text_rotation == 90
        assert ws["B1"].alignment.text_rotation == 45
    finally:
        wb.close()


def test_xlsx_text_orientations_survive_parse_write_parse_roundtrip(tmp_path):
    source = tmp_path / "source_rotation.xlsx"
    roundtripped = tmp_path / "roundtripped_rotation.xlsx"
    _write_source_workbook(source)

    frames = ExcelBackend().read_multi(str(source), header_levels=1)
    ExcelBackend().write_multi(frames, str(roundtripped))
    back = ExcelBackend().read_multi(str(roundtripped), header_levels=1)

    orients = _text_orientations(back)
    assert orients["A1"]["rotation"] == 90
    assert orients["B1"]["rotation"] == 45
    assert back["Data"]["Category"].tolist() == ["alpha"]


def test_xlsx_renderer_keeps_defaults_when_orientation_metadata_is_absent(tmp_path):
    out = tmp_path / "defaults_rotation.xlsx"

    ExcelBackend().write_multi(
        {"Data": pd.DataFrame({"Category": ["alpha"], "Value": [1]})},
        str(out),
    )

    wb = load_workbook(out)
    try:
        ws = wb["Data"]
        assert ws["A1"].alignment.text_rotation in (None, 0)
        assert ws["B1"].alignment.text_rotation in (None, 0)
    finally:
        wb.close()
