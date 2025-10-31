from __future__ import annotations
from spreadsheet_handling.rendering.flow import compose_ir, apply_ir_passes, build_render_plan, default_p1_passes
from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_plan as render_plan_to_xlsx
from tests.utils.xlsx_normalize import normalize_xlsx

import logging

logging.basicConfig(level=logging.DEBUG)

def test_p1_smoke_render_flow(tmp_path):
    domain = {
        "sheets": [
            {
                "name": "Sheet1",
                "headers": ["A", "B", "C"],
                "rows": [["a1", "b1", "c1"]],
                "validations": [{"kind": "list", "col": 2, "values": ["A","B","C"], "from_row": 2, "to_row": 100}],
                "options": {"header_fill_rgb": "#F2F2F2", "freeze_header": True, "auto_filter": True},
                "meta": {"author": "tester"}
            }
        ],
        "workbook_meta": {"version": "0.1.0", "exported_at": "2025-10-28T00:00:00Z", "author": "tester"}
    }

    ir = compose_ir(domain)
    ir = apply_ir_passes(ir, default_p1_passes())
    plan = build_render_plan(ir)

    out = tmp_path / "p1.xlsx"
    render_plan_to_xlsx(plan, str(out))
    print("PLAN OPS:", getattr(plan, "ops", None))  # ← shows if AddValidation exists

    shape = normalize_xlsx(str(out))
    assert "Sheet1" in shape["sheets"]
    hdr = shape["styles"]["Sheet1"]["header"]
    assert hdr["A1"]["value"] == "A"
    assert hdr["A1"]["bold"] is True
    assert "Sheet1" in shape["filters"]
    assert "Sheet1" in shape["freeze"]
    assert shape["freeze"]["Sheet1"].startswith("A2")
    assert "Sheet1" in shape["validations"]
    assert any(v["type"] == "list" for v in shape["validations"]["Sheet1"])
    assert shape["meta"].get("version") is not None
    assert shape["meta"].get("author") is not None
