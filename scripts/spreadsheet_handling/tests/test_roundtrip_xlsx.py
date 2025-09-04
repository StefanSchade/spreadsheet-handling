# scripts/spreadsheet_handling/tests/test_roundtrip_xlsx.py
from pathlib import Path
import json

from spreadsheet_handling.cli.sheets_pack import run_pack
from spreadsheet_handling.cli.sheets_unpack import run_unpack


def test_roundtrip_xlsx(tmp_path: Path):
    # Arrange
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "A.json").write_text(
        json.dumps(
            [
                {"id": 1, "name": "Alpha", "note": "Ä"},
                {"id": 2, "name": "Beta", "note": "Ö"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data_dir / "B.json").write_text(
        json.dumps([{"x": "😀", "y": 1}], ensure_ascii=False),
        encoding="utf-8",
    )

    out_xlsx = tmp_path / "world.xlsx"
    cfg = {
        "workbook": str(out_xlsx),
        "defaults": {"levels": 3, "backend": "xlsx"},
        "sheets": [
            {"json": str(data_dir / "A.json")},
            {"json": str(data_dir / "B.json")},
        ],
    }

    # Act: pack -> unpack
    run_pack(cfg)
    out_json = tmp_path / "out"
    run_unpack(out_xlsx, out_json, levels=3, backend="xlsx")

    # Assert
    a = json.loads((out_json / "A.json").read_text(encoding="utf-8"))
    b = json.loads((out_json / "B.json").read_text(encoding="utf-8"))
    assert a[0]["name"] == "Alpha"
    assert b[0]["x"] == "😀"
