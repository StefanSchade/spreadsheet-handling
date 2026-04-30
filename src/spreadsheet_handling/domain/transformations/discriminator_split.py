"""Split and merge frames by a discriminator column."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from numbers import Number
from typing import Any

import pandas as pd

Frames = dict[str, Any]

_META_KEY = "split_by_discriminator"
_PLACEHOLDER = "{value}"
_INVALID_SEGMENT_CHARS = set("/\\[]:*?")


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


def _value_map_entries(value_map: Mapping[Any, str] | None) -> list[tuple[Any, str]]:
    if not isinstance(value_map, Mapping) or not value_map:
        raise ValueError("value_map must be a non-empty mapping")
    entries: list[tuple[Any, str]] = []
    frame_names: list[str] = []
    for raw_value, raw_frame_name in value_map.items():
        value = _valid_discriminator_value(
            raw_value,
            frame_name="value_map",
            column_name="value_map",
            row_number=len(entries) + 1,
        )
        frame_name = _valid_frame_name(raw_frame_name)
        if any(_values_equal(existing, value) for existing, _ in entries):
            raise ValueError(f"value_map contains duplicate value {value!r}")
        entries.append((value, frame_name))
        frame_names.append(frame_name)
    _ensure_unique_target_frames(frame_names)
    return entries


def _mapped_frame_name(mapped_values: list[tuple[Any, str]] | None, value: Any) -> str:
    assert mapped_values is not None
    for mapped_value, frame_name in mapped_values:
        if _values_equal(mapped_value, value):
            return frame_name
    raise ValueError(f"Discriminator value {value!r} is missing from value_map")


def _frame_for_value(entries: list[dict[str, Any]], value: Any) -> str:
    for entry in entries:
        if _values_equal(entry["value"], value):
            return entry["frame"]
    raise ValueError(f"Discriminator value {value!r} is not configured")


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


def _ensure_source_frames_exist(frames: Mapping[str, Any], entries: list[dict[str, Any]]) -> None:
    missing = [entry["frame"] for entry in entries if entry["frame"] not in frames]
    if missing:
        raise KeyError(f"Configured source frame(s) not found: {missing!r}")


def _ensure_no_existing_target_frames(frames: Mapping[str, Any], target_frames: list[str]) -> None:
    collisions = [frame_name for frame_name in target_frames if frame_name in frames]
    if collisions:
        raise ValueError(f"Generated target frame(s) already exist: {collisions!r}")


def _ensure_unique_target_frames(target_frames: Iterable[str]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for frame_name in target_frames:
        if frame_name in seen:
            duplicates.append(frame_name)
        seen.add(frame_name)
    if duplicates:
        raise ValueError(f"Duplicate generated frame name(s): {duplicates!r}")


def _ensure_pattern(pattern: str, field_name: str) -> None:
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if pattern.count(_PLACEHOLDER) != 1:
        raise ValueError(f"{field_name} must contain exactly one {_PLACEHOLDER!r} placeholder")
    remainder = pattern.replace(_PLACEHOLDER, "")
    if "{" in remainder or "}" in remainder:
        raise ValueError(f"{field_name} contains unsupported format placeholders")


def _pattern_parts(pattern: str) -> tuple[str, str]:
    _ensure_pattern(pattern, "pattern")
    before, after = pattern.split(_PLACEHOLDER, 1)
    return before, after


def _try_value_from_frame_name(pattern: str, frame_name: str) -> str | None:
    before, after = _pattern_parts(pattern)
    if not frame_name.startswith(before) or not frame_name.endswith(after):
        return None
    value = frame_name[len(before) : len(frame_name) - len(after) if after else len(frame_name)]
    if value == "":
        return None
    return value


def _value_from_frame_name(pattern: str, frame_name: str) -> str:
    value = _try_value_from_frame_name(pattern, frame_name)
    if value is None:
        raise ValueError(f"Source frame {frame_name!r} does not match pattern {pattern!r}")
    return value


def _safe_value_segment(value: Any) -> str:
    segment = str(_plain_value(value))
    if (
        not segment
        or segment.strip() != segment
        or any(char in _INVALID_SEGMENT_CHARS for char in segment)
        or any(ord(char) < 32 for char in segment)
    ):
        raise ValueError(
            f"Discriminator value {value!r} is not safe for target_pattern; provide value_map"
        )
    return segment


def _valid_frame_name(frame_name: Any) -> str:
    if not isinstance(frame_name, str) or not frame_name.strip():
        raise ValueError("Generated frame names must be non-empty strings")
    if any(ord(char) < 32 for char in frame_name):
        raise ValueError(f"Generated frame name {frame_name!r} contains control characters")
    return frame_name


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


def _ensure_column(df: pd.DataFrame, column: str, *, frame_name: str) -> None:
    if column not in df.columns:
        raise KeyError(f"Frame {frame_name!r} is missing discriminator column {column!r}")


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Frame {name!r} not found")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Frame {name!r} must be a pandas DataFrame")
    if isinstance(frame.columns, pd.MultiIndex) or any(
        isinstance(col, tuple) for col in frame.columns
    ):
        raise ValueError(f"Frame {name!r} must have flat columns")
    if len(set(frame.columns)) != len(frame.columns):
        raise ValueError(f"Frame {name!r} must not contain duplicate columns")
    return frame


def _split_meta(frames: Mapping[str, Any], config_id: str) -> Mapping[str, Any] | None:
    meta = frames.get("_meta")
    if not isinstance(meta, Mapping):
        return None
    configs = meta.get(_META_KEY)
    if not isinstance(configs, Mapping):
        return None
    config = configs.get(config_id)
    return config if isinstance(config, Mapping) else None


def _write_split_meta(
    out: dict[str, Any],
    *,
    config_id: str,
    payload: dict[str, Any],
) -> None:
    meta = dict(out.get("_meta") or {})
    configs = dict(meta.get(_META_KEY) or {})
    configs[config_id] = payload
    meta[_META_KEY] = configs
    out["_meta"] = meta
