from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR, TableBlock

def test_ir_basic_structure():
    wb = WorkbookIR()
    sh = SheetIR(name="Main")
    sh.tables.append(TableBlock(frame_name="df", top_left=(1,1)))
    wb.sheets["Main"] = sh
    assert "Main" in wb.sheets
    assert wb.sheets["Main"].tables[0].top_left == (1,1)

