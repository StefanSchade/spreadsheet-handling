import pandas as pd
import pytest
from pathlib import Path

@pytest.fixture
def tmpdir_path(tmp_path: Path) -> Path:
    return tmp_path

@pytest.fixture
def df_products():
    return pd.DataFrame([
        {"id": "P-001", "name": "Alpha", "branch_id": "B-001"},
        {"id": "P-002", "name": "Beta",  "branch_id": "B-002"},
    ])

@pytest.fixture
def frames_minimal(df_products):
    return {
        "products": df_products.copy(),
        "branches": pd.DataFrame([
            {"branch_id": "B-001", "manager": "Alice"},
            {"branch_id": "B-002", "manager": "Bob"},
        ])
    }

@pytest.fixture(autouse=True)
def _select_xlsx_backend(request, monkeypatch):
    """If a test is marked xlsx_ir, force the IR backend via env var."""
    if request.node.get_closest_marker("xlsx_ir"):
        monkeypatch.setenv("SH_XLSX_BACKEND", "ir")
    # If a test is marked xlsx_legacy, make sure we use legacy explicitly.
    if request.node.get_closest_marker("xlsx_legacy"):
        monkeypatch.delenv("SH_XLSX_BACKEND", raising=False)
