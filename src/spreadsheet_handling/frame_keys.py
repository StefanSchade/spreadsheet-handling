from __future__ import annotations

from typing import Any, Iterator, Mapping

import pandas as pd

RESERVED_FRAME_KEYS: frozenset[str] = frozenset({"_meta"})


def is_reserved_frame_key(name: object) -> bool:
    return isinstance(name, str) and name in RESERVED_FRAME_KEYS


def iter_data_frames(frames: Mapping[str, Any]) -> Iterator[tuple[str, pd.DataFrame]]:
    for name, value in frames.items():
        if is_reserved_frame_key(name):
            continue
        yield name, value


def copy_reserved_frames(frames: Mapping[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    for name, value in frames.items():
        if is_reserved_frame_key(name):
            out[name] = value
    return out
