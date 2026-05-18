"""``merge_by_discriminator`` orchestration and merge-side derivation.

Merge-side value entries, source-frame selection, column-order resolution, and
row-order restoration. Verbatim move out of the former single
``discriminator_split`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-DISCRIMINATOR-P5). The ordering trio
(``_sorted_entries_for_merge`` / ``_merge_sort_key`` / ``_row_order_positions``)
is kept co-located here; only ``_sort_token`` lives in ``values`` because the
split side also uses it. The persisted ``merge_by_discriminator`` metadata
payload literal stays inline so its canonical shape is unchanged. ``merge``
does *no* conflict reconciliation between source frames: that design space
belongs to FTR-WORKBOOK-VIEW-PAYLOAD-CONFLICT-PRECEDENCE-P6.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from .framecheck import _ensure_source_frames_exist, _require_frame
from .metadata import _split_meta, _write_split_meta
from .naming import (
    _ensure_pattern,
    _try_value_from_frame_name,
    _valid_frame_name,
    _value_from_frame_name,
    _value_map_entries,
)
from .values import _plain_value, _sort_token

Frames = dict[str, Any]


def merge_by_discriminator(
    frames: Mapping[str, Any],
    *,
    target_frame: str,
    discriminator_column: str,
    source_pattern: str,
    value_map: Mapping[Any, str] | None = None,
    source_frames: Iterable[str] | None = None,
    preserve_row_order: bool = True,
    column_order: Iterable[str] | None = None,
    name: str | None = None,
) -> Frames:
    """Merge per-discriminator frames back into one frame."""
    _ensure_pattern(source_pattern, "source_pattern")
    config_id = name or target_frame
    meta = _split_meta(frames, config_id)
    value_entries = _merge_value_entries(
        frames,
        source_pattern=source_pattern,
        value_map=value_map,
        source_frames=source_frames,
        meta=meta,
    )
    if not value_entries:
        raise ValueError(f"No source frames match pattern {source_pattern!r}")

    source_columns = _uniform_source_columns(
        frames,
        entries=value_entries,
        discriminator_column=discriminator_column,
    )
    output_columns = _output_column_order(
        explicit_column_order=column_order,
        meta=meta,
        source_columns=source_columns,
        discriminator_column=discriminator_column,
    )
    order_positions = _row_order_positions(meta) if preserve_row_order else {}

    records_with_order: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for entry in _sorted_entries_for_merge(value_entries, order_positions):
        frame_name = entry["frame"]
        value = entry["value"]
        source = _require_frame(frames, frame_name)
        for row_number, source_row in enumerate(source.to_dict(orient="records")):
            record = {column: source_row[column] for column in source_columns}
            record[discriminator_column] = value
            records_with_order.append(
                (
                    _merge_sort_key(
                        frame_name=frame_name,
                        row_number=row_number,
                        value=value,
                        order_positions=order_positions,
                    ),
                    record,
                )
            )

    ordered_records = [record for _, record in sorted(records_with_order, key=lambda item: item[0])]
    out: dict[str, Any] = dict(frames)
    out[target_frame] = pd.DataFrame(ordered_records, columns=output_columns)
    _write_split_meta(
        out,
        config_id=config_id,
        payload={
            "operation": "merge_by_discriminator",
            "target_frame": target_frame,
            "discriminator_column": discriminator_column,
            "source_pattern": source_pattern,
            "values": value_entries,
            "column_order": output_columns,
            "preserve_row_order": bool(preserve_row_order),
        },
    )
    return out


def _merge_value_entries(
    frames: Mapping[str, Any],
    *,
    source_pattern: str,
    value_map: Mapping[Any, str] | None,
    source_frames: Iterable[str] | None,
    meta: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if value_map is not None:
        entries = [
            {"value": _plain_value(value), "frame": _valid_frame_name(frame_name)}
            for value, frame_name in _value_map_entries(value_map)
        ]
        _ensure_source_frames_exist(frames, entries)
        return entries

    if source_frames is not None:
        frame_names = _source_frame_list(source_frames)
        entries = [
            {
                "value": _plain_value(_value_from_frame_name(source_pattern, frame_name)),
                "frame": frame_name,
            }
            for frame_name in frame_names
        ]
        _ensure_source_frames_exist(frames, entries)
        return entries

    meta_entries = _meta_value_entries(meta)
    if meta_entries:
        _ensure_source_frames_exist(frames, meta_entries)
        return meta_entries

    entries: list[dict[str, Any]] = []
    for frame_name in frames:
        if frame_name == "_meta":
            continue
        value = _try_value_from_frame_name(source_pattern, frame_name)
        if value is None:
            continue
        entries.append({"value": value, "frame": frame_name})
    return sorted(entries, key=lambda entry: _sort_token(entry["value"]))


def _uniform_source_columns(
    frames: Mapping[str, Any],
    *,
    entries: list[dict[str, Any]],
    discriminator_column: str,
) -> list[str]:
    first_columns: list[str] | None = None
    for entry in entries:
        frame_name = entry["frame"]
        source = _require_frame(frames, frame_name)
        if discriminator_column in source.columns:
            raise ValueError(
                f"Source frame {frame_name!r} already contains discriminator column "
                f"{discriminator_column!r}"
            )
        columns = list(source.columns)
        if first_columns is None:
            first_columns = columns
        elif columns != first_columns:
            raise ValueError(
                f"Source frame {frame_name!r} has non-uniform columns {columns!r}; "
                f"expected {first_columns!r}"
            )
    return first_columns or []


def _output_column_order(
    *,
    explicit_column_order: Iterable[str] | None,
    meta: Mapping[str, Any] | None,
    source_columns: list[str],
    discriminator_column: str,
) -> list[str]:
    if explicit_column_order is not None:
        columns = list(explicit_column_order)
    elif isinstance(meta, Mapping) and isinstance(meta.get("column_order"), list):
        columns = list(meta["column_order"])
    else:
        columns = [*source_columns, discriminator_column]

    expected = [*source_columns, discriminator_column]
    if set(columns) != set(expected) or len(columns) != len(expected):
        raise ValueError(
            f"column_order must contain exactly source columns plus discriminator: {expected!r}"
        )
    return columns


def _sorted_entries_for_merge(
    entries: list[dict[str, Any]],
    order_positions: Mapping[tuple[str, int], int],
) -> list[dict[str, Any]]:
    if order_positions:
        return entries
    return sorted(entries, key=lambda entry: _sort_token(entry["value"]))


def _merge_sort_key(
    *,
    frame_name: str,
    row_number: int,
    value: Any,
    order_positions: Mapping[tuple[str, int], int],
) -> tuple[Any, ...]:
    position = order_positions.get((frame_name, row_number))
    if position is not None:
        return (0, position)
    return (1, _sort_token(value), row_number)


def _row_order_positions(meta: Mapping[str, Any] | None) -> dict[tuple[str, int], int]:
    if not isinstance(meta, Mapping):
        return {}
    raw = meta.get("row_order")
    if not isinstance(raw, list):
        return {}
    positions: dict[tuple[str, int], int] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        frame = item.get("frame")
        row_number = item.get("row_number")
        position = item.get("position")
        if isinstance(frame, str) and isinstance(row_number, int) and isinstance(position, int):
            positions[(frame, row_number)] = position
    return positions


def _meta_value_entries(meta: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(meta, Mapping):
        return []
    raw = meta.get("values")
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        frame = item.get("frame")
        if not isinstance(frame, str) or not frame.strip():
            continue
        entries.append({"value": _plain_value(item.get("value")), "frame": frame})
    return entries


def _source_frame_list(source_frames: Iterable[str]) -> list[str]:
    if isinstance(source_frames, (str, bytes)):
        raise TypeError("source_frames must be a list of frame names, not a string")
    frame_names = list(source_frames)
    if not frame_names or any(
        not isinstance(name, str) or not name.strip() for name in frame_names
    ):
        raise ValueError("source_frames must contain non-empty frame names")
    return frame_names
