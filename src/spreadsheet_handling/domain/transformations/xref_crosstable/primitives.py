"""Shared leaf primitives for the ``xref_crosstable`` package.

Decouples ``operation`` and ``dense_axes`` so the package no longer has a
load-time import cycle. Bodies are verbatim moves out of the original flat
module; only their location has changed.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain._cell_primitives import _values_equal

_META_KEY = "xref_crosstable"


def _as_list(value: str | Iterable[Any] | None, field_name: str) -> list[Any]:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, str):
        result = [value]
    else:
        result = list(value)
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Frame {name!r} not found")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Frame {name!r} must be a pandas DataFrame")
    if isinstance(frame.columns, pd.MultiIndex) or any(
        isinstance(col, tuple) for col in frame.columns
    ):
        raise ValueError(
            f"Frame {name!r} has MultiIndex/tuple columns; "
            "FTR-XREF-CROSSTABLE first slice requires flat column labels"
        )
    return frame


def _ensure_flat_axis_labels(values: Iterable[Any], field_name: str) -> None:
    unsupported = [value for value in values if isinstance(value, tuple)]
    if unsupported:
        raise ValueError(
            f"{field_name} contains tuple labels {unsupported!r}; "
            "FTR-XREF-CROSSTABLE first slice requires flat labels"
        )


def _ensure_columns(
    df: pd.DataFrame,
    columns: Iterable[Any],
    *,
    frame_name: str,
    field_name: str,
) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(
            f"Frame {frame_name!r} is missing configured {field_name} columns: "
            f"{missing!r}. row_keys define identity; display labels only roundtrip "
            "when they are configured as row_keys or otherwise carried explicitly."
        )


def _ordered_values_equal(left: Iterable[Any], right: Iterable[Any]) -> bool:
    left_values = list(left)
    right_values = list(right)
    return len(left_values) == len(right_values) and all(
        _values_equal(left_value, right_value)
        for left_value, right_value in zip(left_values, right_values, strict=True)
    )


def _xref_config(
    frames: Mapping[str, Any],
    *config_ids: str,
    relation: str | None = None,
    matrix: str | None = None,
) -> Mapping[str, Any] | None:
    meta = frames.get("_meta")
    if not isinstance(meta, Mapping):
        return None
    configs = meta.get(_META_KEY)
    if not isinstance(configs, Mapping):
        return None

    for config_id in config_ids:
        config = configs.get(config_id)
        if isinstance(config, Mapping):
            return config
    for config in configs.values():
        if not isinstance(config, Mapping):
            continue
        if relation is not None and config.get("relation") == relation:
            return config
        if matrix is not None and config.get("matrix") == matrix:
            return config
    return None
