"""JSON backend integration slice.

Verifies the real JSON directory writer and reader preserve visible tabular
frames through a filesystem roundtrip.
"""

import pandas as pd
from pathlib import Path
from spreadsheet_handling.io_backends.json_backend import write_json_dir, read_json_dir

def test_json_roundtrip(tmp_path: Path):
    frames = {
        "products": pd.DataFrame([{"id":"P-1","name":"Alpha"}, {"id":"P-2","name":"Beta"}]),
        "branches": pd.DataFrame([{"branch_id":"B-1","city":"X"}]),
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))
    back = read_json_dir(str(out))
    assert set(back.keys()) == {"products","branches"}
    assert list(back["products"].columns) == ["id","name"]
    assert back["products"].iloc[0]["name"] == "Alpha"
