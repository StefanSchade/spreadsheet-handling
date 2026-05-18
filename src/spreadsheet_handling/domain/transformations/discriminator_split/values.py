"""Tiny local discriminator-value core.

Shared by ``split``, ``merge`` and ``naming`` (the bijective split/merge
symmetry depends on these being identical for both directions). Behavior is a
verbatim move out of the former single ``discriminator_split`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-DISCRIMINATOR-P5); this is a narrow
package-local core, not a broad shared utility.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Number
from typing import Any

import pandas as pd


def _valid_discriminator_value(
    value: Any,
    *,
    frame_name: str,
    column_name: str,
    row_number: int,
) -> Any:
    value = _plain_value(value)
    if _is_empty_cell(value):
        raise ValueError(
            f"Frame {frame_name!r}, row {row_number}: discriminator column "
            f"{column_name!r} is empty"
        )
    if isinstance(value, (Mapping, list, set, tuple)):
        raise ValueError(
            f"Frame {frame_name!r}, row {row_number}: discriminator column "
            f"{column_name!r} must be scalar"
        )
    return value


def _plain_value(value: Any) -> Any:
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (AttributeError, ValueError, TypeError):
            pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _is_empty_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _sort_token(value: Any) -> tuple[int, Any]:
    value = _plain_value(value)
    if isinstance(value, Number) and not isinstance(value, bool):
        return (0, float(value))
    return (1, str(value))


def _values_equal(left: Any, right: Any) -> bool:
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False
