from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from .base import BackendBase, BackendOptions

Frames = Dict[str, pd.DataFrame]


class JSONBackend(BackendBase):
    """
    Backend for a directory of JSON files, one file per sheet (e.g. products.json).
    """

    def read_multi(self, path: str, header_levels: int, options: BackendOptions | None = None) -> Frames:
        in_dir = Path(path)
        out: Frames = {}
        for p in sorted(in_dir.glob("*.json")):
            df = pd.read_json(p, dtype=str)
            df = df.where(pd.notnull(df), "")  # normalize empties as ""
            out[p.stem] = df
        return out

    def write_multi(self, frames: Frames, path: str, options: BackendOptions | None = None) -> None:
        out_dir = Path(path)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, df in frames.items():
            p = out_dir / f"{name}.json"
            df.to_json(p, orient="records", force_ascii=False)


# ---- Test-facing convenience wrappers (kept for compatibility) ----

def read_json_dir(path: str) -> Frames:
    """
    tests expect: frames = read_json_dir(path)
    """
    opts = BackendOptions()
    return JSONBackend().read_multi(path, header_levels=1, options=opts)


def write_json_dir(path: str, frames: Frames) -> None:
    """
    tests expect: write_json_dir(path, frames)
    """
    opts = BackendOptions()
    JSONBackend().write_multi(frames, path, options=opts)
