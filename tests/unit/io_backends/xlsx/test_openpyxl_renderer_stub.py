from pathlib import Path

import pytest

from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook

pytestmark = pytest.mark.ftr("FTR-IR-WRITEPATH-P1")


@pytest.mark.xlsx_ir
def test_render_stub_creates_file(tmp_path):
    ir = WorkbookIR()
    ir.sheets["Main"] = SheetIR(name="Main")
    plan = build_render_plan(ir)
    out = tmp_path / "out.xlsx"
    render_workbook(plan, out)
    assert out.exists()

