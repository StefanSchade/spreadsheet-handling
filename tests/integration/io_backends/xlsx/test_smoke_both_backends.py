import pytest

@pytest.mark.xlsx_ir
@pytest.mark.xlsx_legacy
@pytest.mark.parametrize("backend", ["legacy","ir"])
def test_smoke_both_backends(tmp_path, backend, monkeypatch):
    if backend == "ir":
        monkeypatch.setenv("SH_XLSX_BACKEND","ir")
    else:
        monkeypatch.delenv("SH_XLSX_BACKEND", raising=False)
    # call ExcelBackend().write_multi(...) and assert basics
