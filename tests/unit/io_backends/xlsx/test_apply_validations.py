# tests/unit/io_backends/xls/test_apply_validations.py
import pandas as pd
import pytest
from openpyxl import load_workbook

from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend

pytestmark = pytest.mark.ftr("FTR-IR-WRITEPATH-P1")


class Frames(dict):
    pass
def test_apply_in_list_validation_smoke(tmp_path):
    frames = Frames({"Kunden": pd.DataFrame({"Kategorie": ["Privat", ""]})})
    frames.meta = {
        "constraints": [
            {
                "sheet": "Kunden",
                "column": "Kategorie",
                "rule": {"type": "in_list", "values": ["Privat", "Gewerblich"]},
            }
        ]
    }

    out = tmp_path / "v.xlsx"
    ExcelBackend().write_multi(frames, str(out))

    wb = load_workbook(out)
    ws = wb["Kunden"]
    assert ws.data_validations and ws.data_validations.dataValidation
