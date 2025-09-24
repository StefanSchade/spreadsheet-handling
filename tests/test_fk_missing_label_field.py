# scripts/spreadsheet_handling/tests/test_fk_missing_label_field.py
from pathlib import Path
import json
import pandas as pd
from spreadsheet_handling.cli.sheets_pack import run_pack


def test_missing_label_field_results_in_none_helper(tmp_path: Path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "ziel.json").write_text(
        json.dumps([{"id": 1}, {"id": 2}], ensure_ascii=False), "utf-8"
    )  # kein "name"
    (d / "quelle.json").write_text(
        json.dumps([{"fk": "id_(Ziel)", "id_(Ziel)": 1}], ensure_ascii=False), "utf-8"
    )

    out_dir = tmp_path / "out"
    cfg = {
        "workbook": str(out_dir),
        "defaults": {"levels": 3, "backend": "csv"},
        "sheets": [
            {"name": "Ziel", "json": str(d / "ziel.json")},
            {"name": "Quelle", "json": str(d / "quelle.json")},
        ],
    }
    run_pack(cfg)
    df = pd.read_csv(out_dir / "Quelle.csv", encoding="utf-8")
    assert "_Ziel_name" in df.columns
    assert pd.isna(df.loc[0, "_Ziel_name"])
