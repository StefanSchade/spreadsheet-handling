# scripts/spreadsheet_handling/tests/test_fk_multi_targets.py
from pathlib import Path
import json
import pandas as pd
from spreadsheet_handling.cli.sheets_pack import run_pack


def test_multiple_fk_helpers(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "orte.json").write_text(
        json.dumps([{"id": 1, "name": "Insel"}, {"id": 2, "name": "Berg"}], ensure_ascii=False),
        "utf-8",
    )
    (data / "kunden.json").write_text(
        json.dumps([{"id": "A", "name": "Anna"}, {"id": "B", "name": "Bob"}], ensure_ascii=False),
        "utf-8",
    )
    (data / "buchungen.json").write_text(
        json.dumps(
            [
                {"nr": 1, "id_(Orte)": 1, "id_(Kunden)": "A"},
                {"nr": 2, "id_(Orte)": 2, "id_(Kunden)": "B"},
            ],
            ensure_ascii=False,
        ),
        "utf-8",
    )

    out_dir = tmp_path / "csv_out"
    cfg = {
        "workbook": str(out_dir),
        "defaults": {"levels": 3, "backend": "csv"},
        "sheets": [
            {"name": "Orte", "json": str(data / "orte.json")},
            {"name": "Kunden", "json": str(data / "kunden.json")},
            {"name": "Buchungen", "json": str(data / "buchungen.json")},
        ],
    }
    run_pack(cfg)
    df = pd.read_csv(out_dir / "Buchungen.csv", encoding="utf-8")
    assert "_Orte_name" in df.columns and "_Kunden_name" in df.columns
    assert df.loc[0, "_Orte_name"] == "Insel" and df.loc[0, "_Kunden_name"] == "Anna"
    assert df.loc[1, "_Orte_name"] == "Berg" and df.loc[1, "_Kunden_name"] == "Bob"
