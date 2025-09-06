# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import json
import pytest

from spreadsheet_handling.cli.sheets_pack import run_pack


def test_pack_fails_on_missing_fk(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    (data_dir / "A.json").write_text(
        json.dumps([{"id": 1, "name": "Alpha"}], ensure_ascii=False), encoding="utf-8"
    )
    (data_dir / "B.json").write_text(
        json.dumps([{"id_(A)": 1}, {"id_(A)": 99}], ensure_ascii=False), encoding="utf-8"
    )

    out_dir = tmp_path / "out_csv"
    cfg = {
        "workbook": str(out_dir),
        "defaults": {
            "levels": 3,
            "backend": "csv",
            "id_field": "id",
            "label_field": "name",
            "helper_prefix": "_",
            "detect_fk": True,
            "validate": {"missing_fk": "fail", "duplicate_ids": "warn"},
        },
        "sheets": [
            {"name": "A", "json": str(data_dir / "A.json")},
            {"name": "B", "json": str(data_dir / "B.json")},
        ],
    }

    with pytest.raises(ValueError):
        run_pack(cfg)
