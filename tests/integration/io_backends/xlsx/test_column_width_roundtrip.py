from __future__ import annotations

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook

from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend


pytestmark = pytest.mark.ftr("FTR-COLUMN-WIDTH-ROUNDTRIP-P4")


def _write_source_workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws["A1"] = "id"
    ws["B1"] = "title"
    ws["A2"] = "P-1"
    ws["B2"] = "Compact matrix label"
    ws.column_dimensions["A"].width = 18.0
    ws.column_dimensions["B"].width = 42.5
    wb.save(path)
    wb.close()


def _column_widths(frames, sheet_name="Data"):
    return frames["_meta"]["sheets"][sheet_name]["column_widths"]


def test_xlsx_column_widths_are_parsed_into_sheet_metadata(tmp_path):
    source = tmp_path / "source_widths.xlsx"
    _write_source_workbook(source)

    frames = ExcelBackend().read_multi(str(source), header_levels=1)

    widths = _column_widths(frames)
    assert widths["A"] == {"width": pytest.approx(18.0), "source": "workbook"}
    assert widths["B"] == {"width": pytest.approx(42.5), "source": "workbook"}


def test_xlsx_renderer_applies_column_width_metadata(tmp_path):
    frames = {
        "Data": pd.DataFrame({"id": ["P-1"], "title": ["Compact matrix label"]}),
        "_meta": {
            "sheets": {
                "Data": {
                    "column_widths": {
                        "A": {"width": 18.0, "source": "workbook"},
                        "B": {"width": 42.5, "source": "workbook"},
                    }
                }
            }
        },
    }
    out = tmp_path / "rendered_widths.xlsx"

    ExcelBackend().write_multi(frames, str(out))

    wb = load_workbook(out)
    try:
        ws = wb["Data"]
        assert ws.column_dimensions["A"].width == pytest.approx(18.0)
        assert ws.column_dimensions["B"].width == pytest.approx(42.5)
    finally:
        wb.close()


def test_xlsx_column_widths_survive_parse_write_parse_roundtrip(tmp_path):
    source = tmp_path / "source_widths.xlsx"
    roundtripped = tmp_path / "roundtripped_widths.xlsx"
    _write_source_workbook(source)

    frames = ExcelBackend().read_multi(str(source), header_levels=1)
    ExcelBackend().write_multi(frames, str(roundtripped))
    back = ExcelBackend().read_multi(str(roundtripped), header_levels=1)

    widths = _column_widths(back)
    assert widths["A"]["width"] == pytest.approx(18.0)
    assert widths["B"]["width"] == pytest.approx(42.5)
    assert back["Data"].to_dict(orient="records") == [
        {"id": "P-1", "title": "Compact matrix label"}
    ]


def test_xlsx_renderer_keeps_defaults_when_width_metadata_is_absent(tmp_path):
    out = tmp_path / "defaults.xlsx"

    ExcelBackend().write_multi(
        {"Data": pd.DataFrame({"id": ["P-1"], "title": ["Alpha"]})},
        str(out),
    )

    wb = load_workbook(out)
    try:
        ws = wb["Data"]
        assert "A" not in ws.column_dimensions
        assert "B" not in ws.column_dimensions
    finally:
        wb.close()
