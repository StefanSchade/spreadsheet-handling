import pandas as pd
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook

def test_compose_creates_one_sheet_per_frame():
    frames = {"A": pd.DataFrame({"x":[1,2]}), "B": pd.DataFrame({"y":[3]})}
    ir = compose_workbook(frames, meta={})
    assert set(ir.sheets.keys()) == {"A","B"}
    assert ir.sheets["A"].tables[0].frame_name == "A"

