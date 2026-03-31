# tests/unit/rendering/passes/test_named_range_pass.py
"""
FTR-NAMED-RANGES — Auto-generated stable named ranges per TableBlock.

Acceptance: names unique, deterministic, and used by formulas/validations.
"""
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR, TableBlock, NamedRange
from spreadsheet_handling.rendering.passes.core import NamedRangePass
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.plan import DefineNamedRange
from spreadsheet_handling.rendering.passes import apply_all
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from spreadsheet_handling.rendering.parse_ir import parse_ir

pytestmark = [pytest.mark.ftr("FTR-NAMED-RANGES")]


# ---------------------------------------------------------------------------
# NamedRangePass unit tests
# ---------------------------------------------------------------------------

class TestNamedRangePass:

    def _make_ir(self) -> WorkbookIR:
        ir = WorkbookIR()
        tbl = TableBlock(
            frame_name="products",
            top=1, left=1,
            header_rows=1, header_cols=1,
            n_rows=4, n_cols=3,
            headers=["id", "name", "price"],
            header_map={"id": 1, "name": 2, "price": 3},
        )
        sh = SheetIR(name="products", tables=[tbl])
        ir.sheets["products"] = sh
        return ir

    def test_generates_three_ranges(self):
        ir = self._make_ir()
        NamedRangePass().apply(ir)
        sh = ir.sheets["products"]
        assert len(sh.named_ranges) == 3

    def test_names_are_deterministic(self):
        ir = self._make_ir()
        NamedRangePass().apply(ir)
        names = {nr.name for nr in ir.sheets["products"].named_ranges}
        assert "products_products_table" in names
        assert "products_products_header" in names
        assert "products_products_body" in names

    def test_table_range_covers_full_area(self):
        ir = self._make_ir()
        NamedRangePass().apply(ir)
        tbl_nr = [nr for nr in ir.sheets["products"].named_ranges if nr.name.endswith("_table")][0]
        assert tbl_nr.area == (1, 1, 4, 3)

    def test_header_range(self):
        ir = self._make_ir()
        NamedRangePass().apply(ir)
        hdr = [nr for nr in ir.sheets["products"].named_ranges if nr.name.endswith("_header")][0]
        assert hdr.area == (1, 1, 1, 3)

    def test_body_range(self):
        ir = self._make_ir()
        NamedRangePass().apply(ir)
        body = [nr for nr in ir.sheets["products"].named_ranges if nr.name.endswith("_body")][0]
        assert body.area == (2, 1, 4, 3)

    def test_names_unique_across_sheets(self):
        ir = WorkbookIR()
        for sname in ["orders", "customers"]:
            tbl = TableBlock(frame_name=sname, top=1, left=1, header_rows=1, n_rows=3, n_cols=2)
            ir.sheets[sname] = SheetIR(name=sname, tables=[tbl])
        NamedRangePass().apply(ir)
        all_names = []
        for sh in ir.sheets.values():
            all_names.extend(nr.name for nr in sh.named_ranges)
        assert len(all_names) == len(set(all_names)), "Named ranges not unique"


# ---------------------------------------------------------------------------
# Render plan emission
# ---------------------------------------------------------------------------

class TestNamedRangeEmission:

    def test_plan_contains_define_named_range_ops(self):
        ir = WorkbookIR()
        tbl = TableBlock(frame_name="data", top=1, left=1, header_rows=1, n_rows=3, n_cols=2)
        ir.sheets["data"] = SheetIR(name="data", tables=[tbl])
        NamedRangePass().apply(ir)
        plan = build_render_plan(ir)
        nr_ops = [op for op in plan.ops if isinstance(op, DefineNamedRange)]
        assert len(nr_ops) == 3


# ---------------------------------------------------------------------------
# End-to-end XLSX roundtrip
# ---------------------------------------------------------------------------

class TestNamedRangeXLSXRoundtrip:

    def test_named_ranges_written_to_xlsx(self, tmp_path: Path, monkeypatch):
        frames = {
            "products": pd.DataFrame([
                {"id": "P-1", "name": "Alpha"},
                {"id": "P-2", "name": "Beta"},
            ]),
        }
        out = tmp_path / "test.xlsx"
        ExcelBackend().write_multi(frames, str(out))

        wb = load_workbook(out)
        names = {name for name in wb.defined_names.keys()}
        assert "products_products_table" in names
        assert "products_products_header" in names
        assert "products_products_body" in names
        wb.close()

    def test_named_ranges_roundtrip_via_parse_ir(self, tmp_path: Path, monkeypatch):
        frames = {
            "products": pd.DataFrame([
                {"id": "P-1", "name": "Alpha"},
            ]),
        }
        out = tmp_path / "test.xlsx"
        ExcelBackend().write_multi(frames, str(out))

        ir = parse_ir(out)
        nr_names = {nr.name for nr in ir.sheets["products"].named_ranges}
        assert "products_products_table" in nr_names
        assert "products_products_body" in nr_names
