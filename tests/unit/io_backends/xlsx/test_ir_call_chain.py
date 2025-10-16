# tests/unit/io_backends/xlsx/test_ir_call_chain.py
import pandas as pd
import pytest

from spreadsheet_handling.io_backends.xlsx_backend import ExcelBackend
import spreadsheet_handling.io_backends.xlsx_backend as xb   # <-- patch THIS module's symbols

@pytest.mark.xlsx_ir
def test_ir_pipeline_is_called(monkeypatch, tmp_path):
    calls = []

    def fake_compose(frames, meta):
        calls.append("compose")
        class _IR: ...
        return _IR()

    def fake_apply_all(ir, meta):
        calls.append("passes")
        return ir

    def fake_render(ir, out_path):
        calls.append("render")
        out_path.write_bytes(b"PK\x03\x04")  # minimal ZIP signature

    # Patch the names that xlsx_backend actually calls
    monkeypatch.setattr(xb, "compose_workbook", fake_compose, raising=True)
    monkeypatch.setattr(xb, "apply_render_passes", fake_apply_all, raising=True)
    monkeypatch.setattr(xb, "render_workbook", fake_render, raising=True)

    frames = {"Sheet1": pd.DataFrame({"a": [1, 2]})}
    out = tmp_path / "book.xlsx"

    ExcelBackend().write_multi(frames, out)

    assert calls == ["compose", "passes", "render"]
    assert out.exists()
