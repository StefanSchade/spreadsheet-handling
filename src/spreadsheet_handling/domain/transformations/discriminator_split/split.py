"""``split_by_discriminator`` orchestration and split-side value entries.

Verbatim move out of the former single ``discriminator_split`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-DISCRIMINATOR-P5). The persisted
``split_by_discriminator`` metadata payload literal is kept inline here (not in
``metadata``) so its canonical shape is unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from .framecheck import (
    _ensure_column,
    _ensure_no_existing_target_frames,
    _ensure_unique_target_frames,
    _require_frame,
)
from .metadata import _write_split_meta
from .naming import (
    _PLACEHOLDER,
    _ensure_pattern,
    _frame_for_value,
    _mapped_frame_name,
    _safe_value_segment,
    _valid_frame_name,
    _value_map_entries,
)
from .values import _plain_value, _valid_discriminator_value, _values_equal

Frames = dict[str, Any]


def split_by_discriminator(
    frames: Mapping[str, Any],
    *,
    source_frame: str,
    discriminator_column: str,
    target_pattern: str,
    value_map: Mapping[Any, str] | None = None,
    preserve_row_order: bool = True,
    name: str | None = None,
) -> Frames:
    """Partition one frame into per-discriminator frames."""
    _ensure_pattern(target_pattern, "target_pattern")
    source = _require_frame(frames, source_frame)
    _ensure_column(source, discriminator_column, frame_name=source_frame)

    value_entries = _split_value_entries(
        source,
        discriminator_column=discriminator_column,
        target_pattern=target_pattern,
        value_map=value_map,
    )
    target_frames = [entry["frame"] for entry in value_entries]
    _ensure_unique_target_frames(target_frames)
    _ensure_no_existing_target_frames(frames, target_frames)

    split_columns = [column for column in source.columns if column != discriminator_column]
    records_by_frame: dict[str, list[dict[str, Any]]] = {
        entry["frame"]: [] for entry in value_entries
    }
    row_order: list[dict[str, int | str]] = []

    for position, source_row in enumerate(source.to_dict(orient="records")):
        value = _valid_discriminator_value(
            source_row[discriminator_column],
            frame_name=source_frame,
            column_name=discriminator_column,
            row_number=position + 1,
        )
        target = _frame_for_value(value_entries, value)
        row_number = len(records_by_frame[target])
        records_by_frame[target].append({column: source_row[column] for column in split_columns})
        if preserve_row_order:
            row_order.append({"frame": target, "row_number": row_number, "position": position})

    out: dict[str, Any] = dict(frames)
    for target in target_frames:
        out[target] = pd.DataFrame(records_by_frame[target], columns=split_columns)

    _write_split_meta(
        out,
        config_id=name or source_frame,
        payload={
            "operation": "split_by_discriminator",
            "source_frame": source_frame,
            "discriminator_column": discriminator_column,
            "target_pattern": target_pattern,
            "source_pattern": target_pattern,
            "values": value_entries,
            "column_order": list(source.columns),
            "split_columns": split_columns,
            "preserve_row_order": bool(preserve_row_order),
            "row_order": row_order if preserve_row_order else [],
        },
    )
    return out


def _split_value_entries(
    source: pd.DataFrame,
    *,
    discriminator_column: str,
    target_pattern: str,
    value_map: Mapping[Any, str] | None,
) -> list[dict[str, Any]]:
    mapped_values = _value_map_entries(value_map) if value_map is not None else None
    entries: list[dict[str, Any]] = []
    for row_number, value in enumerate(source[discriminator_column].tolist(), start=1):
        value = _valid_discriminator_value(
            value,
            frame_name="<source>",
            column_name=discriminator_column,
            row_number=row_number,
        )
        if any(_values_equal(entry["value"], value) for entry in entries):
            continue
        frame_name = (
            _mapped_frame_name(mapped_values, value)
            if mapped_values is not None
            else target_pattern.replace(_PLACEHOLDER, _safe_value_segment(value))
        )
        entries.append({"value": _plain_value(value), "frame": _valid_frame_name(frame_name)})
    return entries
