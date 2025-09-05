from pathlib import Path
import json
import pandas as pd

from spreadsheet_handling.cli.sheets_pack import run_pack


def test_fk_with_custom_id_field(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Zielblatt mit custom ID-Feld "Schluessel"
    (data_dir / "guten_morgen.json").write_text(
        json.dumps(
            [
                {"Schluessel": "A-1", "name": "Alpha"},
                {"Schluessel": "B-2", "name": "Beta"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Quellblatt: FK heißt "Schluessel_(Guten_Morgen)"
    (data_dir / "bestellungen.json").write_text(
        json.dumps(
            [
                {"bestellnr": "B-1", "Schluessel_(Guten_Morgen)": "A-1"},
                {"bestellnr": "B-2", "Schluessel_(Guten_Morgen)": "B-2"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "csv_out"
    cfg = {
        "workbook": str(out_dir),
        "defaults": {
            "levels": 3,
            "backend": "csv",
            "id_field": "Schluessel",
            "label_field": "name",
            "helper_prefix": "_",
            "detect_fk": True,
        },
        "sheets": [
            {"name": "Guten Morgen", "json": str(data_dir / "guten_morgen.json")},
            {"name": "Bestellungen", "json": str(data_dir / "bestellungen.json")},
        ],
    }

    run_pack(cfg)

    df = pd.read_csv(out_dir / "Bestellungen.csv", header=0, encoding="utf-8")
    assert "_Guten_Morgen_name" in df.columns
    assert df.loc[0, "_Guten_Morgen_name"] == "Alpha"
    assert df.loc[1, "_Guten_Morgen_name"] == "Beta"
