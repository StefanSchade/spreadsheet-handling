import pandas as pd
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.passes import apply_all
from spreadsheet_handling.rendering.plan import SetHeader, WriteDataBlock
import pytest

pytestmark = [
    pytest.mark.ftr("FTR-IR-WRITEPATH-P1"),
    pytest.mark.ftr("FTR-LEGEND-BLOCKS"),
]


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


def test_compose_adds_legend_table_block_next_to_data_table():
    frames = {
        "product_matrix": pd.DataFrame({
            "feature": ["currency"],
            "FZ-AD": ["E-R-K"],
        })
    }
    meta = {
        "legend_blocks": {
            "status_codes": {
                "title": "Status Codes",
                "placement": {
                    "sheet": "product_matrix",
                    "anchor": "right_of_table",
                    "target": "product_matrix",
                },
                "entries": [
                    {"token": "E", "label": "Editable", "group": "input"},
                    {"token": "E-R-K", "label": "Capital-path recalculation", "group": "input"},
                    {"token": "x", "label": "Not meaningful", "group": "blocked"},
                ],
            }
        }
    }

    ir = compose_workbook(frames, meta)
    sheet = ir.sheets["product_matrix"]

    assert len(sheet.tables) == 2
    data_table, legend_table = sheet.tables
    assert data_table.kind == "data"
    assert legend_table.kind == "legend"
    assert legend_table.frame_name == "legend_status_codes"
    assert legend_table.top == 1
    assert legend_table.left == 4
    assert legend_table.headers == ["Token", "Meaning", "Group"]
    assert legend_table.data[1] == ["E-R-K", "Capital-path recalculation", "input"]

    resolved = meta["legend_blocks"]["status_codes"]["resolved"]
    assert resolved["sheet"] == "product_matrix"
    assert resolved["top"] == 1
    assert resolved["left"] == 4


def test_compose_rejects_duplicate_legend_tokens():
    frames = {"product_matrix": pd.DataFrame({"feature": ["currency"]})}
    meta = {
        "legend_blocks": {
            "status_codes": {
                "placement": {"sheet": "product_matrix"},
                "entries": [
                    {"token": "E", "label": "Editable"},
                    {"token": "E", "label": "Duplicate"},
                ],
            }
        }
    }

    with pytest.raises(ValueError, match="duplicate token"):
        compose_workbook(frames, meta)


def test_compose_rejects_unknown_legend_target_table():
    frames = {"product_matrix": pd.DataFrame({"feature": ["currency"]})}
    meta = {
        "legend_blocks": {
            "status_codes": {
                "placement": {"sheet": "product_matrix", "target": "missing_matrix"},
                "entries": [{"token": "E", "label": "Editable"}],
            }
        }
    }

    with pytest.raises(ValueError, match="target table"):
        compose_workbook(frames, meta)


def test_render_plan_emits_data_for_data_and_legend_tables():
    frames = {"product_matrix": pd.DataFrame({"feature": ["currency"], "FZ-AD": ["E"]})}
    meta = {
        "legend_blocks": {
            "status_codes": {
                "placement": {"sheet": "product_matrix", "anchor": "right_of_table"},
                "entries": [{"token": "E", "label": "Editable"}],
            }
        }
    }

    ir = compose_workbook(frames, meta)
    apply_all(ir, meta)
    plan = build_render_plan(ir)

    header_ops = [op for op in plan.ops if isinstance(op, SetHeader)]
    data_ops = [op for op in plan.ops if isinstance(op, WriteDataBlock)]

    assert any(op.sheet == "product_matrix" and op.row == 1 and op.col == 4 and op.text == "Token" for op in header_ops)
    assert any(op.sheet == "product_matrix" and op.r1 == 2 and op.c1 == 4 and op.data == (("E", "Editable"),) for op in data_ops)
