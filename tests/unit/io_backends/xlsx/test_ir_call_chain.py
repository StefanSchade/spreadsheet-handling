# tests/unit/io_backends/xlsx/test_ir_call_chain.py
import pandas as pd
import pytest

from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
import spreadsheet_handling.io_backends.xlsx.xlsx_backend as xb   # <-- patch THIS module's symbols

pytestmark = pytest.mark.ftr("FTR-IR-DATA-CELLS")
def test_ir_pipeline_is_called(monkeypatch, tmp_path):
    calls = []

    class _FakeIR:
        sheets = {}
        hidden_sheets = {}

    class _FakePlan:
        ops = []
        sheet_order = []

    def fake_compose(frames, meta):
        calls.append("compose")
        return _FakeIR()

    def fake_apply_all(ir, meta):
        calls.append("passes")
        return ir

    def fake_build_plan(ir):
        calls.append("build_plan")
        return _FakePlan()

    def fake_render(plan, out_path):
        calls.append("render")
        # create a minimal xlsx so the .exists() check works
        from openpyxl import Workbook
        Workbook().save(out_path)

    # Patch the names that xlsx_backend actually calls
    monkeypatch.setattr(xb, "compose_workbook", fake_compose, raising=True)
    monkeypatch.setattr(xb, "apply_render_passes", fake_apply_all, raising=True)
    monkeypatch.setattr(xb, "build_render_plan", fake_build_plan, raising=True)
    monkeypatch.setattr(xb, "render_workbook", fake_render, raising=True)

    frames = {"Sheet1": pd.DataFrame({"a": [1, 2]})}
    out = tmp_path / "book.xlsx"

    ExcelBackend().write_multi(frames, out)

    assert calls == ["compose", "passes", "build_plan", "render"]
    assert out.exists()
