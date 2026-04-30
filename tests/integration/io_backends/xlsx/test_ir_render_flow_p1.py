"""XLSX IR render-flow integration slice.

Exercises the real compose/pass/plan/render path for XLSX output and verifies
the produced workbook shape through the normalizer utility.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.passes import apply_all
from tests.utils.xlsx_normalize import normalize_xlsx

logging.basicConfig(level=logging.DEBUG)

pytestmark = pytest.mark.ftr("FTR-TEST-NAMING-AND-CONVENTIONS-P3C")


def test_xlsx_ir_render_flow_writes_expected_workbook_shape(tmp_path):
    frames = {
        "Sheet1": pd.DataFrame({"A": ["a1"], "B": ["b1"], "C": ["c1"]}),
    }
    meta = {
        "version": "0.1.0",
        "exported_at": "2025-10-28T00:00:00Z",
        "author": "tester",
        "sheets": {
            "Sheet1": {
                "header_fill_rgb": "#F2F2F2",
                "freeze_header": True,
                "auto_filter": True,
            }
        },
        "constraints": [
            {
                "sheet": "Sheet1",
                "column": "B",
                "rule": {"type": "in_list", "values": ["A", "B", "C"]},
            },
        ],
    }

    ir = compose_workbook(frames, meta)
    ir = apply_all(ir, meta)
    plan = build_render_plan(ir)

    out = tmp_path / "p1.xlsx"
    render_workbook(plan, str(out))

    shape = normalize_xlsx(str(out))
    assert "Sheet1" in shape["sheets"]
    hdr = shape["styles"]["Sheet1"]["header"]
    assert hdr["A1"]["value"] == "A"
    assert hdr["A1"]["bold"] is True
    assert "Sheet1" in shape["filters"]
    assert "Sheet1" in shape["freeze"]
    assert shape["freeze"]["Sheet1"].startswith("A2")
    assert "Sheet1" in shape["validations"]
    assert any(v["type"] == "list" for v in shape["validations"]["Sheet1"])
    assert shape["meta"].get("version") is not None
    assert shape["meta"].get("author") is not None
