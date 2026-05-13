from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR
from spreadsheet_handling.rendering.passes import ValidationPass
import pytest

pytestmark = pytest.mark.ftr("FTR-IR-WRITEPATH-P1")


def test_validation_pass_adds_legacy_list_validation():
    ir = WorkbookIR()
    ir.sheets["S"] = SheetIR(
        name="S",
        meta={
            "_p1_validations": [
                {
                    "kind": "list",
                    "col": 2,
                    "from_row": 3,
                    "to_row": 5,
                    "values": ["A", "B"],
                }
            ]
        },
    )
    ValidationPass().apply(ir)
    validation = ir.sheets["S"].validations[0]
    assert validation.kind == "list"
    assert validation.area == (3, 2, 5, 2)
    assert validation.allow_empty is True
