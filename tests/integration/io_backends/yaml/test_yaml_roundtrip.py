from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from spreadsheet_handling.io_backends.yaml_backend import (
    load_yaml_dir,
    save_yaml_dir,
)

Frames = Dict[str, pd.DataFrame]


def test_yaml_roundtrip(tmp_path: Path) -> None:
    frames: Frames = {
        "products": pd.DataFrame([{"id": "P1", "name": "A"}, {"id": "P2", "name": "B"}]),
        "branches": pd.DataFrame([{"branch_id": "B1", "city": "X"}]),
        "empty": pd.DataFrame([]),
    }

    out = tmp_path / "data"
    save_yaml_dir(frames, str(out))

    loaded = load_yaml_dir(str(out))
    assert set(loaded.keys()) == set(frames.keys())

    for k in frames.keys():
        a = frames[k].fillna("").sort_index(axis=1)
        b = loaded[k].fillna("").sort_index(axis=1)
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))
