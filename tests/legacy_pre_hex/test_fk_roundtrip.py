from pathlib import Path
import json

from spreadsheet_handling.cli.sheets_pack import run_pack
from spreadsheet_handling.cli.sheets_unpack import run_unpack


def test_roundtrip_xlsx_drops_helper_columns(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    (data_dir / "guten_morgen.json").write_text(
        json.dumps([{"id": 1, "name": "Alpha"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (data_dir / "bestellungen.json").write_text(
        json.dumps([{"bestellnr": "B-1", "id_(Guten_Morgen)": 1}], ensure_ascii=False),
        encoding="utf-8",
    )

    out_xlsx = tmp_path / "world.xlsx"
    cfg = {
        "workbook": str(out_xlsx),
        "defaults": {
            "levels": 3,
            "backend": "xlsx",
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

    out_json = tmp_path / "out"
    run_unpack(out_xlsx, out_json, levels=3, backend="xlsx")

    # Bestellungen.json soll KEINE Helper-Spalte enthalten – nur die Originalfelder
    bestellungen = json.loads((out_json / "Bestellungen.json").read_text(encoding="utf-8"))
    assert bestellungen == [{"bestellnr": "B-1", "id_(Guten_Morgen)": 1}]
