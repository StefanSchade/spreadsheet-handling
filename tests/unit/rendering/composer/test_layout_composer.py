import pandas as pd
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook

def test_compose_creates_one_sheet_per_frame():
    frames = {"A": pd.DataFrame({"x":[1,2]}), "B": pd.DataFrame({"y":[3]})}
    ir = compose_workbook(frames, meta={})
    assert set(ir.sheets.keys()) == {"A","B"}
    assert ir.sheets["A"].tables[0].frame_name == "A"


def test_compose_multiindex_builds_header_grid_and_header_rows():
    cols = pd.MultiIndex.from_tuples([
        ("order", "id"),
        ("order", "date"),
        ("customer", "name"),
    ])
    frames = {"Orders": pd.DataFrame([["O1", "2026-01-01", "Alice"]], columns=cols)}

    ir = compose_workbook(frames, meta={})
    sh = ir.sheets["Orders"]
    t = sh.tables[0]

    assert t.header_rows == 2
    assert t.n_rows == 3  # 2 header rows + 1 data row
    assert "__header_grid" in sh.meta
    grid = sh.meta["__header_grid"]
    assert grid[0] == ["order", "order", "customer"]
    assert grid[1] == ["id", "date", "name"]
    assert (1, 1, 1, 2) in sh.meta.get("__header_merges", [])

