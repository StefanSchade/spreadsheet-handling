from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from tools.domain_contracts.check_contracts import BOOLEAN_FIELDS


def _coerce_bool(value: Any) -> bool | Any:
    if isinstance(value, bool):
        return value
    text = "" if value is None else str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return value


def normalize_reimported_contract_frames(frames: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize spreadsheet carrier values before writing staging JSON."""
    out: dict[str, Any] = {
        name: frame.copy() if isinstance(frame, pd.DataFrame) else frame
        for name, frame in frames.items()
        if name != "_meta"
    }
    for frame_name, fields in BOOLEAN_FIELDS.items():
        frame = out.get(frame_name)
        if not isinstance(frame, pd.DataFrame):
            continue
        for field in fields:
            if field in frame.columns:
                frame[field] = frame[field].map(_coerce_bool)
    return out

