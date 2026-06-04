"""ODS column-width and text-orientation roundtrip integration tests."""

from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.io_backends.ods.odf_renderer import render_workbook
from spreadsheet_handling.io_backends.ods.odf_parser import parse_workbook
from spreadsheet_handling.rendering.plan import (
    RenderPlan,
    DefineSheet,
    SetHeader,
    SetColumnWidth,
    SetTextOrientation,
    WriteDataBlock,
)


pytestmark = pytest.mark.ftr("FTR-TEXT-ORIENTATION-ROUNDTRIP-P5")


# ---------------------------------------------------------------------------
# Column width
# ---------------------------------------------------------------------------

def test_ods_column_widths_survive_render_parse_roundtrip(tmp_path):
    plan = RenderPlan()
    plan.add(DefineSheet(sheet="Sheet1", order=0))
    plan.add(SetHeader(sheet="Sheet1", row=1, col=1, text="Col A"))
    plan.add(SetHeader(sheet="Sheet1", row=1, col=2, text="Col B"))
    plan.add(SetColumnWidth(sheet="Sheet1", col=1, width=20.0))
    plan.add(SetColumnWidth(sheet="Sheet1", col=2, width=10.0))
    plan.add(WriteDataBlock(sheet="Sheet1", r1=2, c1=1, data=(("x", "y"),)))

    out = tmp_path / "widths.ods"
    render_workbook(plan, out)

    ir = parse_workbook(out)
    widths = ir.sheets["Sheet1"].meta["__column_widths"]
    assert widths["A"]["width"] == pytest.approx(20.0, abs=0.5)
    assert widths["B"]["width"] == pytest.approx(10.0, abs=0.5)


def test_ods_column_widths_survive_backend_roundtrip(tmp_path):
    frames = {
        "Data": pd.DataFrame({"id": ["P-1"], "title": ["Long label"]}),
        "_meta": {
            "sheets": {
                "Data": {
                    "column_widths": {
                        "A": {"width": 18.0, "source": "workbook"},
                        "B": {"width": 35.0, "source": "workbook"},
                    }
                }
            }
        },
    }
    out = tmp_path / "widths_backend.ods"
    OdsBackend().write_multi(frames, str(out))

    back = OdsBackend().read_multi(str(out), header_levels=1)
    widths = back["_meta"]["sheets"]["Data"]["column_widths"]
    assert widths["A"]["width"] == pytest.approx(18.0, abs=0.5)
    assert widths["B"]["width"] == pytest.approx(35.0, abs=0.5)
    assert back["Data"].to_dict(orient="records") == [{"id": "P-1", "title": "Long label"}]


# ---------------------------------------------------------------------------
# Text orientation
# ---------------------------------------------------------------------------

def test_ods_text_orientations_survive_render_parse_roundtrip(tmp_path):
    plan = RenderPlan()
    plan.add(DefineSheet(sheet="Sheet1", order=0))
    plan.add(SetHeader(sheet="Sheet1", row=1, col=1, text="Rotated"))
    plan.add(SetTextOrientation(sheet="Sheet1", row=1, col=1, rotation=90))
    plan.add(WriteDataBlock(sheet="Sheet1", r1=2, c1=1, data=(("x",),)))

    out = tmp_path / "rotation.ods"
    render_workbook(plan, out)

    ir = parse_workbook(out)
    orients = ir.sheets["Sheet1"].meta["__text_orientations"]
    assert orients["A1"]["rotation"] == 90


def test_ods_text_orientations_survive_backend_roundtrip(tmp_path):
    frames = {
        "Data": pd.DataFrame({"Category": ["alpha"]}),
        "_meta": {
            "sheets": {
                "Data": {
                    "text_orientations": {
                        "A1": {"rotation": 90, "source": "workbook"},
                    }
                }
            }
        },
    }
    out = tmp_path / "rotation_backend.ods"
    OdsBackend().write_multi(frames, str(out))

    back = OdsBackend().read_multi(str(out), header_levels=1)
    orients = back["_meta"]["sheets"]["Data"]["text_orientations"]
    assert orients["A1"]["rotation"] == 90
    assert back["Data"].to_dict(orient="records") == [{"Category": "alpha"}]
