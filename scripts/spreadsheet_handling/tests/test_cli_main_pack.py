from pathlib import Path
import json
from spreadsheet_handling.cli import sheets_pack as cli


def test_cli_main_pack_csv(tmp_path: Path):
    # Daten vorbereiten (Dateinamen -> Sheetnamen in lowercase!)
    (tmp_path / "guten_morgen.json").write_text(
        json.dumps(
            [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}],
            ensure_ascii=False,
        ),
        "utf-8",
    )
    (tmp_path / "bestellungen.json").write_text(
        json.dumps(
            [
                {"bestellnr": "B-1", "id_(Guten_Morgen)": 1},
                {"bestellnr": "B-2", "id_(Guten_Morgen)": 2},
            ],
            ensure_ascii=False,
        ),
        "utf-8",
    )
    out_dir = tmp_path / "out_csv"

    # Aufruf wie: <json_dir> -o <workbook>
    rc = cli.main([str(tmp_path), "-o", str(out_dir), "--backend", "csv"])
    assert rc == 0

    # Erwartete Dateien (lowercase, weil von Dateinamen abgeleitet)
    names = {p.name for p in out_dir.glob("*.csv")}
    assert {"guten_morgen.csv", "bestellungen.csv"} <= names

