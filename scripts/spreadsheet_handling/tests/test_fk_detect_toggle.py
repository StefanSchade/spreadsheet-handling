# scripts/spreadsheet_handling/tests/test_fk_detect_toggle.py
from pathlib import Path
import json
import pandas as pd
from spreadsheet_handling.cli.sheets_pack import run_pack


def test_detect_fk_disabled(tmp_path: Path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "ziel.json").write_text(
        json.dumps([{"id": 1, "name": "Alpha"}], ensure_ascii=False), "utf-8"
    )
    (d / "q.json").write_text(json.dumps([{"id_(Ziel)": 1}], ensure_ascii=False), "utf-8")
    out = tmp_path / "out"
    cfg = {
        "workbook": str(out),
        "defaults": {"levels": 3, "backend": "csv", "detect_fk": False},
        "sheets": [
            {"name": "Ziel", "json": str(d / "ziel.json")},
            {"name": "Q", "json": str(d / "q.json")},
        ],
    }
    run_pack(cfg)
    df = pd.read_csv(out / "Q.csv", encoding="utf-8")
    assert all(not c.startswith("_") for c in df.columns)
