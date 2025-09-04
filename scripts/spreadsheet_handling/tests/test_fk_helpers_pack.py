from pathlib import Path
import json
import pandas as pd

from spreadsheet_handling.cli.sheets_pack import run_pack


def test_fk_helper_is_added_in_csv(tmp_path: Path):
    # Sheets: "Guten Morgen" (Ziel), "Bestellungen" (Quelle mit FK)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Zielblatt: hat id + name
    (data_dir / "guten_morgen.json").write_text(
        json.dumps(
            [
                {"id": 1, "name": "Alpha"},
                {"id": 2, "name": "Beta"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Quellblatt: FK-Spalte id_(Guten_Morgen)
    (data_dir / "bestellungen.json").write_text(
        json.dumps(
            [
                {"bestellnr": "B-1", "id_(Guten_Morgen)": 1},
                {"bestellnr": "B-2", "id_(Guten_Morgen)": 2},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "out_csv"
    cfg = {
        "workbook": str(out_dir),  # für csv nutzen wir Ordner
        "defaults": {
            "levels": 3,
            "backend": "csv",
            "id_field": "id",
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

    # Prüfen: Bestellungen.csv enthält Helper-Spalte "_Guten_Morgen_name" mit Alpha/Beta
    df = pd.read_csv(out_dir / "Bestellungen.csv", header=0, encoding="utf-8")
    assert "_Guten_Morgen_name" in df.columns
    assert df.loc[0, "_Guten_Morgen_name"] == "Alpha"
    assert df.loc[1, "_Guten_Morgen_name"] == "Beta"

