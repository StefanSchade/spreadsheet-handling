"""Pure resolver for canonical XRef axis keys and visible label tuples."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.tabular import ensure_unique_physical_column_labels

from .model import (
    AxisMappingError,
    AxisMappingIntent,
    AxisOrderPolicy,
    ResolvedAxisMapping,
    ResolvedAxisMember,
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


def _safe_repr(value: Any) -> str:
    try:
        rendered = repr(value)
    except Exception:
        return f"<{type(value).__name__} with unavailable repr>"
    if len(rendered) > 160:
        return f"{rendered[:157]}..."
    return rendered


def _is_missing_scalar(value: Any) -> bool:
    if value is None:
        return True
    if not pd.api.types.is_scalar(value):
        return False
    try:
        missing = pd.isna(value)
        return bool(missing)
    except Exception:
        return False


def _has_reflexive_unambiguous_equality(value: Any) -> bool:
    try:
        return bool(value == value)
    except Exception:
        return False


def _is_hashable(value: Any) -> bool:
    try:
        hash(value)
    except Exception:
        return False
    return True


def _text_value_diagnostic(value: Any) -> str:
    if _is_missing_scalar(value):
        return f"missing value {_safe_repr(value)}"

    problems: list[str] = []
    if not pd.api.types.is_scalar(value):
        problems.append("non-scalar")
    if not _has_reflexive_unambiguous_equality(value):
        problems.append("ambiguous equality")
    if not _is_hashable(value):
        problems.append("unhashable")
    if problems:
        return f"{'/'.join(problems)} value {_safe_repr(value)}"
    if not isinstance(value, str):
        return f"non-string value {_safe_repr(value)} ({type(value).__name__})"
    if not value.strip():
        return f"empty value {_safe_repr(value)}"
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
    if _is_missing_scalar(value):
        raise AxisMappingError(
            f"Axis mapping source frame {source_frame!r} row {row_position} "
            f"order column {column!r} contains missing value {_safe_repr(value)}"
        )
    if not pd.api.types.is_scalar(value):
        raise AxisMappingError(
            f"Axis mapping source frame {source_frame!r} row {row_position} "
            f"order column {column!r} contains non-scalar value {_safe_repr(value)}"
        )
    if not _has_reflexive_unambiguous_equality(value):
        raise AxisMappingError(
            f"Axis mapping source frame {source_frame!r} row {row_position} "
            f"order column {column!r} has ambiguous or non-reflexive equality "
            f"for value {_safe_repr(value)}"
        )
    return value


def _column_position(columns: Sequence[Any], configured: str) -> int | None:
    for position, column in enumerate(columns):
        try:
            equal = bool(column == configured)
        except Exception:
            equal = False
        if equal:
            return position
    return None


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
    except Exception as exc:
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
        position = _column_position(physical_columns, configured)
        if position is None:
            if configured not in missing:
                missing.append(configured)
            continue
        positions[configured] = position
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


def _strictly_less(left: tuple[Any, ...], right: tuple[Any, ...]) -> bool:
    try:
        return bool(left < right)
    except Exception:
        return False


def _configured_order(
    records: Sequence[_SourceRecord],
    *,
    intent: AxisMappingIntent,
) -> list[_SourceRecord]:
    try:
        ordered = sorted(records, key=lambda record: record.configured_sort_key)
        reverse_input_ordered = sorted(
            reversed(records),
            key=lambda record: record.configured_sort_key,
        )
    except Exception as exc:
        raise AxisMappingError(
            f"Axis mapping source frame {intent.source_frame!r} order columns "
            f"{list(intent.order_columns)!r} cannot be compared deterministically: "
            f"{type(exc).__name__}: {exc}"
        ) from None

    ordered_keys = [record.key for record in ordered]
    reverse_ordered_keys = [record.key for record in reverse_input_ordered]
    adjacent_are_strict = all(
        _strictly_less(left.configured_sort_key, right.configured_sort_key)
        for left, right in zip(ordered, ordered[1:])
    )
    if ordered_keys != reverse_ordered_keys or not adjacent_are_strict:
        raise AxisMappingError(
            f"Axis mapping source frame {intent.source_frame!r} order columns "
            f"{list(intent.order_columns)!r} do not define deterministic, "
            "strictly comparable ordering values; canonical key tie-breaking "
            "could not establish a total order"
        )
    return ordered


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
    if not isinstance(intent, AxisMappingIntent):
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
