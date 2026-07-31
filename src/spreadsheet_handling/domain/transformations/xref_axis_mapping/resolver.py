"""Pure resolver for canonical XRef axis keys and visible label tuples."""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd

from spreadsheet_handling.domain.tabular import ensure_unique_physical_column_labels

from .model import (
    AxisMappingError,
    AxisMappingIntent,
    AxisOrderPolicy,
    ResolvedAxisMapping,
    ResolvedAxisMember,
    _unsupported_type_detail,
)


class _ExactNumpyIntegerTypes:
    """Deduplicated exact types with identity-only membership."""

    def __init__(self, candidates: Iterable[type[Any]]) -> None:
        distinct: list[type[Any]] = []
        for candidate in candidates:
            if not any(candidate is existing for existing in distinct):
                distinct.append(candidate)
        self._types = tuple(distinct)

    def __contains__(self, candidate: object) -> bool:
        return any(candidate is supported for supported in self._types)

    def __iter__(self) -> Iterator[type[Any]]:
        return iter(self._types)

    def __len__(self) -> int:
        return len(self._types)


_SUPPORTED_EXACT_NUMPY_INTEGER_TYPES = _ExactNumpyIntegerTypes(
    np.dtype(type_code).type for type_code in np.typecodes["AllInteger"]
)
_EXACT_NUMPY_FLOAT_TYPES = (
    np.float16,
    np.float32,
    np.float64,
)


@dataclass(frozen=True)
class _SourceRecord:
    key: str
    labels: tuple[str, ...]
    order_values: tuple[Any, ...]
    source_position: int

    @property
    def configured_sort_key(self) -> tuple[Any, ...]:
        return (*self.order_values, self.key)


def _is_exact_nan(value: Any) -> bool:
    if type(value) is float:
        return math.isnan(value)
    if any(type(value) is value_type for value_type in _EXACT_NUMPY_FLOAT_TYPES):
        return bool(np.isnan(value))
    return False


def _text_value_diagnostic(value: Any) -> str:
    if value is None or value is pd.NA:
        return "missing value"
    if _is_exact_nan(value):
        return "missing value"
    if type(value) is not str:
        return _unsupported_type_detail()
    if not str.strip(value):
        return "empty value"
    return ""


def _require_source_text(
    value: Any,
    *,
    source_frame: str,
    row_position: int,
    column: str,
    role: str,
) -> str:
    diagnostic = _text_value_diagnostic(value)
    if diagnostic:
        raise AxisMappingError(
            f"Axis mapping source frame {source_frame!r} row {row_position} "
            f"{role} column {column!r} must contain a non-empty string; "
            f"got {diagnostic}"
        )
    return value


def _require_order_value(
    value: Any,
    *,
    source_frame: str,
    row_position: int,
    column: str,
) -> Any:
    if value is None or value is pd.NA:
        raise AxisMappingError(
            f"Axis mapping source frame {source_frame!r} row {row_position} "
            f"order column {column!r} contains a missing value"
        )
    if _is_exact_nan(value):
        raise AxisMappingError(
            f"Axis mapping source frame {source_frame!r} row {row_position} "
            f"order column {column!r} contains a missing value"
        )
    if type(value) in _SUPPORTED_EXACT_NUMPY_INTEGER_TYPES:
        return int(value)
    if type(value) is not str and type(value) is not int:
        raise AxisMappingError(
            f"Axis mapping source frame {source_frame!r} row {row_position} "
            f"order column {column!r} must contain exact built-in string or "
            f"integer values; got {_unsupported_type_detail()}"
        )
    return value


def _column_positions(columns: Sequence[Any], configured: str) -> tuple[int, ...]:
    return tuple(
        position
        for position, column in enumerate(columns)
        if type(column) is str and column == configured
    )


def _require_source_frame(
    frames: Mapping[str, Any],
    intent: AxisMappingIntent,
) -> tuple[pd.DataFrame, dict[str, int]]:
    if not isinstance(frames, Mapping):
        raise AxisMappingError("Axis mapping frames must be a mapping")
    if intent.source_frame not in frames:
        raise AxisMappingError(
            f"Axis mapping source frame {intent.source_frame!r} was not found"
        )
    source = frames[intent.source_frame]
    if not isinstance(source, pd.DataFrame):
        raise AxisMappingError(
            f"Axis mapping source frame {intent.source_frame!r} must be a pandas DataFrame"
        )
    try:
        ensure_unique_physical_column_labels(
            source,
            frame_name=intent.source_frame,
        )
    except ValueError as exc:
        raise AxisMappingError(f"Invalid axis mapping source: {exc}") from None

    configured_columns = (
        intent.key_column,
        *intent.label_columns,
        *intent.order_columns,
    )
    physical_columns = source.columns.tolist()
    positions: dict[str, int] = {}
    missing: list[str] = []
    for configured in configured_columns:
        matching_positions = _column_positions(physical_columns, configured)
        if not matching_positions:
            if configured not in missing:
                missing.append(configured)
            continue
        if len(matching_positions) > 1:
            raise AxisMappingError(
                f"Axis mapping source frame {intent.source_frame!r} has "
                f"ambiguous duplicate exact matches for configured column "
                f"{configured!r} at positions {list(matching_positions)!r}"
            )
        positions[configured] = matching_positions[0]
    if missing:
        raise AxisMappingError(
            f"Axis mapping source frame {intent.source_frame!r} is missing "
            f"configured column(s) {missing!r}"
        )
    return source, positions


def _materialize_used_keys(used_keys: Iterable[Any] | None) -> tuple[str, ...]:
    if used_keys is None:
        return ()
    if isinstance(used_keys, (str, bytes)):
        candidates: tuple[Any, ...] = (used_keys,)
    else:
        try:
            candidates = tuple(used_keys)
        except TypeError:
            raise AxisMappingError(
                "used_keys must be an iterable of canonical axis keys"
            ) from None
    validated: list[str] = []
    for position, value in enumerate(candidates):
        diagnostic = _text_value_diagnostic(value)
        if diagnostic:
            raise AxisMappingError(
                f"used_keys[{position}] must be a non-empty string canonical "
                f"axis key; got {diagnostic}"
            )
        validated.append(value)
    return tuple(validated)


def _read_source_records(
    source: pd.DataFrame,
    *,
    intent: AxisMappingIntent,
    positions: Mapping[str, int],
) -> list[_SourceRecord]:
    records: list[_SourceRecord] = []
    for row_position in range(len(source.index)):
        key = _require_source_text(
            source.iloc[row_position, positions[intent.key_column]],
            source_frame=intent.source_frame,
            row_position=row_position,
            column=intent.key_column,
            role="canonical key",
        )
        labels = tuple(
            _require_source_text(
                source.iloc[row_position, positions[column]],
                source_frame=intent.source_frame,
                row_position=row_position,
                column=column,
                role="visible label",
            )
            for column in intent.label_columns
        )
        order_values = tuple(
            _require_order_value(
                source.iloc[row_position, positions[column]],
                source_frame=intent.source_frame,
                row_position=row_position,
                column=column,
            )
            for column in intent.order_columns
        )
        records.append(
            _SourceRecord(
                key=key,
                labels=labels,
                order_values=order_values,
                source_position=row_position,
            )
        )
    return records


def _ensure_bijection(records: Sequence[_SourceRecord], *, source_frame: str) -> None:
    key_positions: dict[str, int] = {}
    label_keys: dict[tuple[str, ...], str] = {}
    for record in records:
        previous_position = key_positions.get(record.key)
        if previous_position is not None:
            raise AxisMappingError(
                f"Axis mapping source frame {source_frame!r} contains duplicate "
                f"canonical key {record.key!r} at rows {previous_position} and "
                f"{record.source_position}"
            )
        key_positions[record.key] = record.source_position

        previous_key = label_keys.get(record.labels)
        if previous_key is not None:
            raise AxisMappingError(
                f"Axis mapping source frame {source_frame!r} maps canonical "
                f"keys {previous_key!r} and {record.key!r} to duplicate complete "
                f"visible label tuple {record.labels!r}"
            )
        label_keys[record.labels] = record.key


def _ensure_homogeneous_order_columns(
    records: Sequence[_SourceRecord],
    *,
    intent: AxisMappingIntent,
) -> None:
    for column_index, column in enumerate(intent.order_columns):
        value_types = {
            type(record.order_values[column_index])
            for record in records
        }
        if len(value_types) <= 1:
            continue
        type_names = sorted(
            "int" if value_type is int else "str" for value_type in value_types
        )
        raise AxisMappingError(
            f"Axis mapping source frame {intent.source_frame!r} order column "
            f"{column!r} must use one exact supported type for every row; "
            f"got mixed types {type_names!r}"
        )


def _configured_order(
    records: Sequence[_SourceRecord],
    *,
    intent: AxisMappingIntent,
) -> list[_SourceRecord]:
    _ensure_homogeneous_order_columns(records, intent=intent)
    return sorted(records, key=lambda record: record.configured_sort_key)


def _ordered_records(
    records: Sequence[_SourceRecord],
    *,
    intent: AxisMappingIntent,
) -> list[_SourceRecord]:
    if intent.order_policy is AxisOrderPolicy.SOURCE_ROW:
        return list(records)
    return _configured_order(records, intent=intent)


def _ensure_used_keys_present(
    used_keys: Sequence[str],
    *,
    records: Sequence[_SourceRecord],
    source_frame: str,
) -> None:
    available = {record.key for record in records}
    missing: list[str] = []
    for key in used_keys:
        if key not in available and key not in missing:
            missing.append(key)
    if missing:
        raise AxisMappingError(
            f"Used canonical axis key(s) {missing!r} are missing from axis "
            f"mapping source frame {source_frame!r}"
        )


def resolve_axis_mapping(
    frames: Mapping[str, Any],
    intent: AxisMappingIntent,
    *,
    used_keys: Iterable[Any] | None = None,
) -> ResolvedAxisMapping:
    """Resolve a complete, ordered, immutable key/label bijection.

    ``used_keys`` optionally checks the completeness of the mapping for a
    caller's current axis vocabulary. It does not filter the resolved source
    members.

    The resolver reads only. It returns no Frames and writes no metadata.
    """
    if type(intent) is not AxisMappingIntent:
        raise AxisMappingError("intent must be an AxisMappingIntent")
    validated_used_keys = _materialize_used_keys(used_keys)
    source, positions = _require_source_frame(frames, intent)
    records = _read_source_records(
        source,
        intent=intent,
        positions=positions,
    )
    _ensure_bijection(records, source_frame=intent.source_frame)
    ordered = _ordered_records(records, intent=intent)
    _ensure_used_keys_present(
        validated_used_keys,
        records=ordered,
        source_frame=intent.source_frame,
    )
    members = tuple(
        ResolvedAxisMember(
            key=record.key,
            labels=record.labels,
            position=position,
        )
        for position, record in enumerate(ordered)
    )
    return ResolvedAxisMapping(
        label_columns=intent.label_columns,
        members=members,
    )
