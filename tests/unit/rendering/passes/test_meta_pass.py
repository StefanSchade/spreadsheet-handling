from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR
from spreadsheet_handling.rendering.passes import MetaPass
import pytest

pytestmark = pytest.mark.ftr("FTR-IR-WRITEPATH-P1")


def test_meta_pass_keeps_hidden_meta_sheet():
    ir = WorkbookIR()
    ir.hidden_sheets["_meta"] = SheetIR(name="_meta")
    MetaPass().apply(ir)
    assert "_meta" in ir.hidden_sheets
