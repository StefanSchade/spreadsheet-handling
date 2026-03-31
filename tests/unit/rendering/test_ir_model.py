from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR, TableBlock
import pytest

pytestmark = pytest.mark.ftr("FTR-IR-WRITEPATH-P1")


def test_ir_basic_structure():
    wb = WorkbookIR()
    sh = SheetIR(name="Main")
    sh.tables.append(TableBlock(frame_name="df", top=1, left=1))
    wb.sheets["Main"] = sh
    assert "Main" in wb.sheets
    assert wb.sheets["Main"].tables[0].top == 1
    assert wb.sheets["Main"].tables[0].left == 1

