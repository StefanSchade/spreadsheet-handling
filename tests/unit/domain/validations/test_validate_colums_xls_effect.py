# tests/unit/domain/validations/test_validate_colums_xls_effect.py
import pandas as pd
from openpyxl import load_workbook
import pytest

from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend

class Frames(dict):
    """Dict-like frames that can also carry .meta."""
    pass

@pytest.mark.xlsx_legacy
def test_xlsx_validations_applied(tmp_path):
    # 1) frames + meta
    frames = Frames({"Kunden": pd.DataFrame({"Kategorie": ["Privat", ""]})})
    frames.meta = {
        "constraints": [
            {
                "sheet": "Kunden",
                "column": "Kategorie",
                "rule": {"type": "in_list", "values": ["Privat", "Gewerblich"]},
                "on_violation": "error",
            }
        ]
    }

    # 2) write xlsx via real backend
    out = tmp_path / "t.xlsx"
    ExcelBackend().write_multi(frames, str(out))

    # 3) re-open and assert there is at least one data validation on the sheet
    wb = load_workbook(out)
    ws = wb["Kunden"]
    assert ws.data_validations is not None
    assert ws.data_validations.dataValidation  # non-empty
