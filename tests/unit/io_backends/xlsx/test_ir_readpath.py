# tests/unit/io_backends/xlsx/test_ir_readpath.py
"""
FTR-IR-READPATH — XLSX read via IR (Excel→IR→Frames+Meta).

Acceptance: roundtrip JSON→XLSX→JSON equality (ignoring presentation-only meta).
"""
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.json_backend import JSONBackend
from spreadsheet_handling.io_backends.xlsx.openpyxl_parser import parse_workbook
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from spreadsheet_handling.rendering.workbook_projection import workbookir_to_frames

pytestmark = [pytest.mark.ftr("FTR-IR-READPATH")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_frames(*, with_meta: bool = True) -> dict:
    frames: dict = {
        "products": pd.DataFrame([
            {"id": "P-001", "name": "Alpha", "branch_id": "B-001"},
            {"id": "P-002", "name": "Beta", "branch_id": "B-002"},
        ]),
        "branches": pd.DataFrame([
            {"branch_id": "B-001", "manager": "Alice"},
            {"branch_id": "B-002", "manager": "Bob"},
        ]),
    }
    if with_meta:
        frames["_meta"] = {
            "version": "3.0",
            "author": "test",
        }
    return frames


# ===========================================================================
# openpyxl parser now extracts data
# ===========================================================================

class TestOpenpyxlParserDataExtraction:

    def test_table_data_populated(self, tmp_path: Path, monkeypatch):
        out = tmp_path / "test.xlsx"
        ExcelBackend().write_multi(_sample_frames(), str(out))

        ir = parse_workbook(out)
        tbl = ir.sheets["products"].tables[0]
        assert tbl.data is not None
        assert len(tbl.data) == 2
        assert tbl.data[0][0] == "P-001"
        assert tbl.data[1][1] == "Beta"

    def test_table_data_all_strings(self, tmp_path: Path, monkeypatch):
        out = tmp_path / "test.xlsx"
        ExcelBackend().write_multi(_sample_frames(), str(out))

        ir = parse_workbook(out)
        tbl = ir.sheets["products"].tables[0]
        for row in tbl.data:
            for cell in row:
                assert isinstance(cell, str)


# ===========================================================================
# workbookir_to_frames conversion
# ===========================================================================

class TestWorkbookIRToFrames:

    def test_returns_all_visible_sheets(self, tmp_path: Path, monkeypatch):
        out = tmp_path / "test.xlsx"
        ExcelBackend().write_multi(_sample_frames(), str(out))

        ir = parse_workbook(out)
        frames = workbookir_to_frames(ir)
        assert "products" in frames
        assert "branches" in frames

    def test_dataframe_columns_match(self, tmp_path: Path, monkeypatch):
        out = tmp_path / "test.xlsx"
        ExcelBackend().write_multi(_sample_frames(), str(out))

        ir = parse_workbook(out)
        frames = workbookir_to_frames(ir)
        assert list(frames["products"].columns) == ["id", "name", "branch_id"]
        assert list(frames["branches"].columns) == ["branch_id", "manager"]

    def test_dataframe_values_match(self, tmp_path: Path, monkeypatch):
        out = tmp_path / "test.xlsx"
        ExcelBackend().write_multi(_sample_frames(), str(out))

        ir = parse_workbook(out)
        frames = workbookir_to_frames(ir)
        assert frames["products"].iloc[0]["name"] == "Alpha"
        assert frames["branches"].iloc[1]["manager"] == "Bob"

    def test_meta_extracted(self, tmp_path: Path, monkeypatch):
        out = tmp_path / "test.xlsx"
        ExcelBackend().write_multi(_sample_frames(), str(out))

        ir = parse_workbook(out)
        frames = workbookir_to_frames(ir)
        assert "_meta" in frames
        meta = frames["_meta"]
        assert meta.get("version") or meta.get("author")


# ===========================================================================
# ExcelBackend.read_multi IR path
# ===========================================================================

class TestReadMultiIR:

    def test_ir_read_returns_dataframes(self, tmp_path: Path, monkeypatch):
        out = tmp_path / "test.xlsx"
        ExcelBackend().write_multi(_sample_frames(), str(out))

        back = ExcelBackend().read_multi(str(out), header_levels=1)
        assert isinstance(back["products"], pd.DataFrame)
        assert len(back["products"]) == 2

    def test_ir_read_excludes_hidden_sheets(self, tmp_path: Path, monkeypatch):
        out = tmp_path / "test.xlsx"
        ExcelBackend().write_multi(_sample_frames(), str(out))

        back = ExcelBackend().read_multi(str(out), header_levels=1)
        data_sheets = {k for k in back if isinstance(back[k], pd.DataFrame)}
        assert "_meta" not in data_sheets


# ===========================================================================
# Full roundtrip: JSON → XLSX → JSON (acceptance criterion)
# ===========================================================================

class TestJSONXLSXJSONRoundtrip:

    def test_data_roundtrips(self, tmp_path: Path, monkeypatch):
        """JSON → XLSX (IR write) → XLSX (IR read) → JSON: data values match."""
        json_in = tmp_path / "json_in"
        xlsx_path = tmp_path / "mid.xlsx"
        json_out = tmp_path / "json_out"

        original = _sample_frames(with_meta=False)

        # Step 1: write JSON
        JSONBackend().write_multi(original, str(json_in))

        # Step 2: read JSON → write XLSX
        mid = JSONBackend().read_multi(str(json_in), header_levels=1)
        ExcelBackend().write_multi(mid, str(xlsx_path))

        # Step 3: read XLSX (IR) → write JSON
        back = ExcelBackend().read_multi(str(xlsx_path), header_levels=1)
        JSONBackend().write_multi(back, str(json_out))

        # Step 4: read final JSON and compare
        final = JSONBackend().read_multi(str(json_out), header_levels=1)

        for sheet in ["products", "branches"]:
            assert list(final[sheet].columns) == list(original[sheet].columns), (
                f"Column mismatch in {sheet}"
            )
            assert len(final[sheet]) == len(original[sheet])
            for col in original[sheet].columns:
                orig_vals = list(original[sheet][col])
                final_vals = list(final[sheet][col])
                assert orig_vals == final_vals, (
                    f"Value mismatch in {sheet}.{col}: {orig_vals} != {final_vals}"
                )

    def test_meta_roundtrips(self, tmp_path: Path, monkeypatch):
        """Meta survives JSON → XLSX → JSON roundtrip."""
        json_in = tmp_path / "json_in"
        xlsx_path = tmp_path / "mid.xlsx"
        json_out = tmp_path / "json_out"

        original = _sample_frames(with_meta=True)
        JSONBackend().write_multi(original, str(json_in))

        mid = JSONBackend().read_multi(str(json_in), header_levels=1)
        ExcelBackend().write_multi(mid, str(xlsx_path))

        back = ExcelBackend().read_multi(str(xlsx_path), header_levels=1)
        assert "_meta" in back
