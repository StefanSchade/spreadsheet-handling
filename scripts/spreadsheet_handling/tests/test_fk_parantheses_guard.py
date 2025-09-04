from pathlib import Path
import json
import pytest

from spreadsheet_handling.cli.sheets_pack import run_pack


def test_parentheses_in_non_fk_column_are_rejected(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    (data_dir / "guten_morgen.json").write_text(
        json.dumps([{"id": 1, "name": "Alpha"}], ensure_ascii=False),
        encoding="utf-8",
    )
    # Nicht-FK-Spalte mit Klammern -> soll fehlschlagen
    (data_dir / "bestellungen.json").write_text(
        json.dumps([{"x(y)": 1, "id_(Guten_Morgen)": 1}], ensure_ascii=False),
        encoding="utf-8",
    )

    out_dir = tmp_path / "csv_out"
    cfg = {
        "workbook": str(out_dir),
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

    with pytest.raises(ValueError) as excinfo:
        run_pack(cfg)
    assert "nicht erlaubt" in str(excinfo.value)

