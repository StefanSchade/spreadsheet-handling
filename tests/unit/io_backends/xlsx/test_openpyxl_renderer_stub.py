from pathlib import Path

import pytest

from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR
from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook

@pytest.mark.xlsx_ir
def test_render_stub_creates_file(tmp_path):
    ir = WorkbookIR()
    ir.sheets["Main"] = SheetIR(name="Main")
    out = tmp_path / "out.xlsx"
    render_workbook(ir, out)
    assert out.exists()

