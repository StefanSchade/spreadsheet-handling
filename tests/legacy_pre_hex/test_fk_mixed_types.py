# scripts/spreadsheet_handling/tests/test_fk_mixed_types.py
from pathlib import Path
import json
import pandas as pd
from spreadsheet_handling.cli.sheets_pack import run_pack


def test_mixed_id_types_match(tmp_path: Path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "ziel.json").write_text(
        json.dumps([{"id": "1", "name": "Alpha"}], ensure_ascii=False), "utf-8"
    )
    (d / "q.json").write_text(json.dumps([{"id_(Ziel)": 1}], ensure_ascii=False), "utf-8")  # int
    out = tmp_path / "out"
    cfg = {
        "workbook": str(out),
        "defaults": {"levels": 3, "backend": "csv"},
        "sheets": [
            {"name": "Ziel", "json": str(d / "ziel.json")},
            {"name": "Q", "json": str(d / "q.json")},
        ],
    }
    run_pack(cfg)
    df = pd.read_csv(out / "Q.csv", encoding="utf-8")
    assert df.loc[0, "_Ziel_name"] == "Alpha"
