from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR
from spreadsheet_handling.rendering.passes import meta_pass

def test_meta_pass_keeps_hidden_meta_sheet():
    ir = WorkbookIR()
    ir.hidden_sheets["_meta"] = SheetIR(name="_meta")
    meta_pass.apply(ir, {"foo": "bar"})
    assert "_meta" in ir.hidden_sheets

