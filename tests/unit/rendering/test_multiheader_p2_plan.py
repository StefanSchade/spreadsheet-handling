from __future__ import annotations

import pandas as pd

from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.passes import apply_all


def test_build_render_plan_emits_multirow_headers_and_merges() -> None:
    cols = pd.MultiIndex.from_tuples([
        ("order", "id"),
        ("order", "date"),
        ("customer", "name"),
    ])
    frames = {"Orders": pd.DataFrame([["O1", "2026-01-01", "Alice"]], columns=cols)}
    meta = {"sheets": {"Orders": {"freeze_header": True, "auto_filter": True}}}

    ir = compose_workbook(frames, meta)
    ir = apply_all(ir, meta)
    plan = build_render_plan(ir)

    headers = [op for op in plan.ops if type(op).__name__ == "SetHeader" and op.sheet == "Orders"]
    merges = [op for op in plan.ops if type(op).__name__ == "MergeCells" and op.sheet == "Orders"]
    freezes = [op for op in plan.ops if type(op).__name__ == "SetFreeze" and op.sheet == "Orders"]

    # 2 rows x 3 columns, but one top-row label is repeated and emitted once after merge logic
    assert any(op.row == 1 and op.col == 1 and op.text == "order" for op in headers)
    assert any(op.row == 2 and op.col == 1 and op.text == "id" for op in headers)
    assert any(op.row == 2 and op.col == 2 and op.text == "date" for op in headers)
    assert any(op.row == 2 and op.col == 3 and op.text == "name" for op in headers)

    # Merge top header cells A1:B1 for "order"
    assert any((m.r1, m.c1, m.r2, m.c2) == (1, 1, 1, 2) for m in merges)

    # Freeze must happen below all header rows (row 3 for 2-row header)
    assert any(f.row == 3 and f.col == 1 for f in freezes)
