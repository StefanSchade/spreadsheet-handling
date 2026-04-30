import pandas as pd
import pytest
from openpyxl import load_workbook

from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend

pytestmark = [
    pytest.mark.ftr("FTR-CLEANUP-IR-P4"),
    pytest.mark.ftr("FTR-TEST-NAMING-AND-CONVENTIONS-P3C"),
]


class Frames(dict):
    """Dict-like frames that can also carry .meta."""

    pass


def test_xlsx_backend_applies_data_validations(tmp_path):
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

    out = tmp_path / "t.xlsx"
    ExcelBackend().write_multi(frames, str(out))

    wb = load_workbook(out)
    ws = wb["Kunden"]
    assert ws.data_validations is not None
    assert ws.data_validations.dataValidation
