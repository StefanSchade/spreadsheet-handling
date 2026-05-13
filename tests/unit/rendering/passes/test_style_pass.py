from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR
from spreadsheet_handling.rendering.passes import StylePass
import pytest

pytestmark = pytest.mark.ftr("FTR-IR-WRITEPATH-P1")


def test_style_pass_adds_default_style_meta():
    ir = WorkbookIR()
    ir.sheets["S"] = SheetIR(name="S")
    StylePass().apply(ir)
    assert ir.sheets["S"].meta["__style"] == {
        "header": {"bold": True, "fill": "#F2F2F2"},
        "legend_header": {"bold": True, "fill": "#D9EAD3"},
    }
