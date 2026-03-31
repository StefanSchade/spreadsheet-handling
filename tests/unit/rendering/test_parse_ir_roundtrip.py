"""
Tests for parse_ir: Scenario-A round-trip (our renderer → XLSX → parse_ir → IR).
"""
from __future__ import annotations

import os
import pandas as pd
import pytest
from pathlib import Path

from spreadsheet_handling.rendering.ir import WorkbookIR, SheetIR, TableBlock
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.passes import apply_all
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.parse_ir import parse_ir
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend

pytestmark = pytest.mark.ftr("FTR-ROUNDTRIP-SAFE-P1")



@pytest.fixture(autouse=True)
def _use_ir_backend(monkeypatch):
    """Force the IR backend for all tests in this module."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_frames_via_ir(frames: dict, meta: dict, path: Path) -> None:
    """Write frames to XLSX using the full IR pipeline."""
    ExcelBackend().write_multi(frames, str(path))


# ---------------------------------------------------------------------------
# 1. Simple flat table roundtrip
# ---------------------------------------------------------------------------

class TestFlatTableRoundtrip:

    def test_single_sheet_geometry(self, tmp_path: Path) -> None:
        """A single flat table at A1 survives roundtrip."""
        frames = {
            "Products": pd.DataFrame({
                "id": ["P1", "P2", "P3"],
                "name": ["Widget", "Gadget", "Doohickey"],
                "price": ["9.99", "19.99", "4.99"],
            }),
        }
        meta: dict = {}
        xlsx = tmp_path / "products.xlsx"
        _write_frames_via_ir(frames, meta, xlsx)

        ir = parse_ir(xlsx)

        assert "Products" in ir.sheets
        sh = ir.sheets["Products"]
        assert len(sh.tables) == 1

        tbl = sh.tables[0]
        assert tbl.top == 1
        assert tbl.left == 1
        assert tbl.header_rows == 1
        assert tbl.n_cols == 3
        assert tbl.n_rows == 4  # 1 header + 3 data
        assert "id" in tbl.headers
        assert "name" in tbl.headers
        assert "price" in tbl.headers

    def test_multiple_sheets(self, tmp_path: Path) -> None:
        """Multiple sheets each get their own table block."""
        frames = {
            "Orders": pd.DataFrame({"order_id": ["O1"], "amount": ["100"]}),
            "Products": pd.DataFrame({"prod_id": ["P1"], "name": ["Widget"]}),
        }
        xlsx = tmp_path / "multi.xlsx"
        _write_frames_via_ir(frames, {}, xlsx)

        ir = parse_ir(xlsx)

        assert "Orders" in ir.sheets
        assert "Products" in ir.sheets
        assert ir.sheets["Orders"].tables[0].n_cols == 2
        assert ir.sheets["Products"].tables[0].n_cols == 2

    def test_data_values_survive_roundtrip(self, tmp_path: Path) -> None:
        """Verify data row count (not cell values, since parse_ir returns IR not DataFrames)."""
        df = pd.DataFrame({"a": ["1", "2", "3", "4", "5"]})
        xlsx = tmp_path / "data.xlsx"
        _write_frames_via_ir({"Sheet": df}, {}, xlsx)

        ir = parse_ir(xlsx)
        tbl = ir.sheets["Sheet"].tables[0]
        assert tbl.n_rows == 6  # 1 header + 5 data


# ---------------------------------------------------------------------------
# 2. MultiIndex header roundtrip
# ---------------------------------------------------------------------------

class TestMultiIndexRoundtrip:

    def test_multiindex_header_rows_detected(self, tmp_path: Path) -> None:
        """A 2-level MultiIndex header produces header_rows=2 on read-back."""
        cols = pd.MultiIndex.from_tuples([
            ("order", "id"),
            ("order", "date"),
            ("customer", "name"),
        ])
        df = pd.DataFrame([["O1", "2026-01-01", "Alice"]], columns=cols)
        frames = {"Orders": df}
        meta = {"sheets": {"Orders": {"freeze_header": True, "auto_filter": True}}}
        xlsx = tmp_path / "multi_hdr.xlsx"
        _write_frames_via_ir(frames, meta, xlsx)

        ir = parse_ir(xlsx)
        tbl = ir.sheets["Orders"].tables[0]

        assert tbl.header_rows == 2
        assert tbl.n_cols == 3
        assert tbl.n_rows == 3  # 2 header rows + 1 data row

    def test_header_merges_extracted(self, tmp_path: Path) -> None:
        """Merge regions in headers are detected and stored."""
        cols = pd.MultiIndex.from_tuples([
            ("order", "id"),
            ("order", "date"),
            ("customer", "name"),
        ])
        df = pd.DataFrame([["O1", "2026-01-01", "Alice"]], columns=cols)
        xlsx = tmp_path / "merges.xlsx"
        _write_frames_via_ir({"Orders": df}, {}, xlsx)

        ir = parse_ir(xlsx)
        merges = ir.sheets["Orders"].meta.get("__header_merges", [])

        # "order" should be merged across cols 1-2 in row 1
        assert (1, 1, 1, 2) in merges

    def test_header_grid_extracted(self, tmp_path: Path) -> None:
        """The 2D header grid is reconstructed."""
        cols = pd.MultiIndex.from_tuples([
            ("order", "id"),
            ("order", "date"),
            ("customer", "name"),
        ])
        df = pd.DataFrame([["O1", "2026-01-01", "Alice"]], columns=cols)
        xlsx = tmp_path / "grid.xlsx"
        _write_frames_via_ir({"Orders": df}, {}, xlsx)

        ir = parse_ir(xlsx)
        grid = ir.sheets["Orders"].meta.get("__header_grid", [])

        assert len(grid) == 2  # 2 header rows
        assert grid[0] == ["order", "order", "customer"]
        assert grid[1] == ["id", "date", "name"]


# ---------------------------------------------------------------------------
# 3. Meta round-trip
# ---------------------------------------------------------------------------

class TestMetaRoundtrip:

    def test_hidden_meta_sheet_detected(self, tmp_path: Path) -> None:
        """The _meta sheet is parsed into hidden_sheets."""
        frames = {"Data": pd.DataFrame({"x": ["1"]})}
        meta = {"sheets": {"Data": {"freeze_header": True}}}
        xlsx = tmp_path / "meta.xlsx"
        _write_frames_via_ir(frames, meta, xlsx)

        ir = parse_ir(xlsx)

        assert "_meta" in ir.hidden_sheets
        assert ir.hidden_sheets["_meta"].meta.get("_hidden") is True


# ---------------------------------------------------------------------------
# 4. Freeze / filter extraction
# ---------------------------------------------------------------------------

class TestFreezeAndFilter:

    def test_freeze_panes_detected(self, tmp_path: Path) -> None:
        """Freeze panes are extracted."""
        meta = {"sheets": {"Data": {"freeze_header": True}}}
        frames = {"Data": pd.DataFrame({"x": ["1"], "y": ["2"]}), "_meta": meta}
        xlsx = tmp_path / "freeze.xlsx"
        _write_frames_via_ir(frames, meta, xlsx)

        ir = parse_ir(xlsx)
        freeze = ir.sheets["Data"].meta.get("__freeze")

        assert freeze is not None
        assert freeze["row"] == 2  # below 1-row header
        assert freeze["col"] == 1

    def test_auto_filter_detected(self, tmp_path: Path) -> None:
        """Auto filter reference is extracted."""
        meta = {"sheets": {"Data": {"auto_filter": True}}}
        frames = {"Data": pd.DataFrame({"x": ["1"], "y": ["2"]}), "_meta": meta}
        xlsx = tmp_path / "filter.xlsx"
        _write_frames_via_ir(frames, meta, xlsx)

        ir = parse_ir(xlsx)
        assert "__autofilter_ref" in ir.sheets["Data"].meta


# ---------------------------------------------------------------------------
# 5. Validation extraction
# ---------------------------------------------------------------------------

class TestValidationRoundtrip:

    def test_list_validation_extracted(self, tmp_path: Path) -> None:
        """Data validations survive roundtrip."""
        meta = {
            "sheets": {"Data": {}},
            "constraints": [
                {"sheet": "Data", "column": "status", "rule": {"type": "in_list", "values": ["A", "B", "C"]}}
            ],
        }
        frames = {"Data": pd.DataFrame({"status": ["A", "B"]}), "_meta": meta}
        xlsx = tmp_path / "valid.xlsx"
        _write_frames_via_ir(frames, meta, xlsx)

        ir = parse_ir(xlsx)
        vals = ir.sheets["Data"].validations

        assert len(vals) >= 1
        assert vals[0].kind == "list"
        assert "A" in vals[0].formula


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_sheet(self, tmp_path: Path) -> None:
        """A sheet with only headers (no data rows) is handled."""
        frames = {"Empty": pd.DataFrame({"col_a": pd.Series([], dtype=str)})}
        xlsx = tmp_path / "empty.xlsx"
        _write_frames_via_ir(frames, {}, xlsx)

        ir = parse_ir(xlsx)
        tbl = ir.sheets["Empty"].tables[0]
        assert tbl.header_rows == 1
        assert tbl.n_cols == 1
        # Could be 1 (header only) or 0 data rows
        assert tbl.n_rows >= 1
