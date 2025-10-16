from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR
from spreadsheet_handling.rendering.passes import validation_pass

def test_validation_pass_is_noop_for_now():
    ir = WorkbookIR()
    ir.sheets["S"] = SheetIR(name="S")
    validation_pass.apply(ir, {})
    assert ir.sheets["S"].validations == []

