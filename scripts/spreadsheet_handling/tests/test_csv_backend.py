from pathlib import Path
import json
import pandas as pd

from spreadsheet_handling.core.flatten import flatten_json
from spreadsheet_handling.core.df_build import build_df_from_records
from spreadsheet_handling.core.unflatten import df_to_objects
from spreadsheet_handling.io_backends.csv_backend import CSVBackend

def normalize(o):
    if isinstance(o, dict):
        return {k: normalize(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [normalize(x) for x in o]
    return o

def test_csv_roundtrip_unicode_and_multirow(tmp_path: Path):
    samples = [
        {
            "kunde": {"name": "Rexi 🦖", "adresse": {"straße": "T-Rex-Weg", "stadt": "Dinohausen"}},
            "bestellung": {"id": "ORD-001", "datum": "2025-08-31"},
        },
        {
            "kunde": {"name": "Galli", "adresse": {"straße": "Windgasse", "stadt": "Pelagia"}},
            "bestellung": {"id": "ORD-002", "datum": "2025-09-01"},
        },
    ]
    records = [flatten_json(s) for s in samples]
    df = build_df_from_records(records, levels=3)

    csv_path = tmp_path / "tmp.csv"
    CSVBackend().write(df, str(csv_path))
    df_back = CSVBackend().read(str(csv_path), header_levels=3)

    out = [normalize(x) for x in df_to_objects(df_back)]
    assert out == [normalize(s) for s in samples]

