from pathlib import Path
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

def _area_to_ref(area):
    # area: (r1,c1,r2,c2) -> 'A1:A500' or rectangular ranges
    r1, c1, r2, c2 = area
    c1l = get_column_letter(c1)
    c2l = get_column_letter(c2)
    if r1 == r2 and c1 == c2:
        return f"{c1l}{r1}"
    return f"{c1l}{r1}:{c2l}{r2}"

def render_workbook(ir, out_path: Path):
    wb = Workbook()
    # remove the default sheet; we'll recreate based on IR
    default = wb.active
    wb.remove(default)

    # create sheets and (optionally) some content
    for name, sheet_ir in ir.sheets.items():
        ws = wb.create_sheet(title=name)
        # write a header cell to ensure sheet is non-empty (not required, but harmless)
        if not ws.max_row:
            ws["A1"] = " "

        # apply validations
        for dv_spec in sheet_ir.validations:
            if dv_spec.kind == "list":
                dv = DataValidation(type="list",
                                    formula1=dv_spec.formula,
                                    allow_blank=dv_spec.allow_empty)
                ws.add_data_validation(dv)
                dv.add(_area_to_ref(dv_spec.area))

    # Hidden sheets & meta can follow; for now we skip
    wb.save(out_path)
