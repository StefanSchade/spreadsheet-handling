"""Small declarative tabular view operations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain._cell_primitives import _is_empty_cell
from spreadsheet_handling.domain.frame_lifecycle import (
    mark_source_if_unclassified,
    write_frame_lifecycle,
)

Frames = dict[str, Any]

_DUPLICATE_POLICIES = {"fail", "aggregate"}
_AGGREGATIONS = {"first", "join"}


def pivot_frame(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    index_columns: str | Iterable[str],
    column_key: str,
    value_column: str,
    column_keys: Iterable[Any] | None = None,
    fill_value: Any = "",
    duplicates: str = "fail",
    aggregation: str = "join",
    separator: str = " | ",
    lifecycle: Mapping[str, Any] | None = None,
    name: str | None = None,
) -> Frames:
    """Pivot a long-form frame into a bounded display view."""
    source_df = _require_frame(frames, source)
    index_cols = _string_list(index_columns, "index_columns")
    _ensure_string(column_key, "column_key")
    _ensure_string(value_column, "value_column")
    _ensure_distinct_input_columns(index_cols, column_key=column_key, value_column=value_column)
    _ensure_columns(
        source_df,
        [*index_cols, column_key, value_column],
        frame_name=source,
        field_name="index_columns/column_key/value_column",
    )
    _ensure_duplicate_policy(duplicates, aggregation, separator)

    pivot_columns = (
        _validate_column_keys(column_keys, field_name="column_keys")
        if column_keys is not None
        else _ordered_pivot_keys(
            source_df[column_key].tolist(), frame_name=source, column_key=column_key
        )
    )
    _ensure_no_output_collisions(index_cols, pivot_columns, output=output)
    _ensure_no_unexpected_pivot_keys(
        source_df[column_key].tolist(),
        pivot_columns,
        source=source,
        column_key=column_key,
    )

    row_values, cell_values, duplicate_cells = _collect_cells(
        source_df,
        index_columns=index_cols,
        column_key=column_key,
        value_column=value_column,
    )
    if duplicate_cells and duplicates == "fail":
        raise ValueError(
            f"Frame {source!r} contains duplicate pivot cells for "
            f"index_columns={index_cols!r} and column_key={column_key!r}: "
            f"{duplicate_cells[:5]!r}"
        )

    records: list[dict[Any, Any]] = []
    for row_token, row_record in row_values:
        record = dict(row_record)
        for pivot_col in pivot_columns:
            cell_key = (row_token, _hashable_token(pivot_col, field_name=column_key))
            values = cell_values.get(cell_key, [])
            record[pivot_col] = _aggregate_cell_values(
                values,
                fill_value=fill_value,
                aggregation=aggregation,
                separator=separator,
            )
        records.append(record)

    result = pd.DataFrame(records, columns=[*index_cols, *pivot_columns])
    result = result.where(pd.notnull(result), "")

    out: dict[str, Any] = dict(frames)
    out[output] = result
    _write_lifecycle(
        out,
        source=source,
        output=output,
        lifecycle=lifecycle,
        step_name=name or "pivot_frame",
    )
    return out


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
    duplicates = _duplicate_column_names(frame)
    if duplicates:
        raise ValueError(f"Frame {name!r} must not contain duplicate columns: {duplicates!r}")
    return frame


def _string_list(value: str | Iterable[str], field_name: str) -> list[str]:
    if isinstance(value, str):
        result = [value]
    else:
        result = list(value)
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    invalid = [item for item in result if not isinstance(item, str) or not item.strip()]
    if invalid:
        raise ValueError(f"{field_name} must contain non-empty strings: {invalid!r}")
    duplicates = [item for item in dict.fromkeys(item for item in result if result.count(item) > 1)]
    if duplicates:
        raise ValueError(f"{field_name} must not contain duplicate column names: {duplicates!r}")
    return result


def _ensure_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _ensure_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    *,
    frame_name: str,
    field_name: str,
) -> None:
    requested = list(columns)
    missing = [column for column in requested if column not in frame.columns]
    if missing:
        raise KeyError(
            f"Frame {frame_name!r} is missing configured {field_name} column(s): {missing!r}"
        )


def _ensure_distinct_input_columns(
    index_columns: list[str],
    *,
    column_key: str,
    value_column: str,
) -> None:
    configured = [*index_columns, column_key, value_column]
    duplicates = [
        item for item in dict.fromkeys(item for item in configured if configured.count(item) > 1)
    ]
    if duplicates:
        raise ValueError(
            f"Pivot input columns must be distinct; duplicate configuration: {duplicates!r}"
        )


def _ensure_duplicate_policy(duplicates: str, aggregation: str, separator: str) -> None:
    if duplicates not in _DUPLICATE_POLICIES:
        raise ValueError(
            f"duplicates must be one of {sorted(_DUPLICATE_POLICIES)!r}; got {duplicates!r}"
        )
    if aggregation not in _AGGREGATIONS:
        raise ValueError(
            f"aggregation must be one of {sorted(_AGGREGATIONS)!r}; got {aggregation!r}"
        )
    if not isinstance(separator, str):
        raise TypeError("separator must be a string")


def _ordered_pivot_keys(values: Iterable[Any], *, frame_name: str, column_key: str) -> list[Any]:
    keys: list[Any] = []
    tokens: set[Any] = set()
    for value in values:
        label = _validate_column_label(value, field_name=column_key, frame_name=frame_name)
        token = _hashable_token(label, field_name=column_key)
        if token in tokens:
            continue
        tokens.add(token)
        keys.append(label)
    return keys


def _validate_column_keys(values: Iterable[Any], *, field_name: str) -> list[Any]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a list of column labels, not a scalar")
    labels = list(values)
    if not labels:
        raise ValueError(f"{field_name} must not be empty")
    result: list[Any] = []
    tokens: set[Any] = set()
    for value in labels:
        label = _validate_column_label(value, field_name=field_name, frame_name=None)
        token = _hashable_token(label, field_name=field_name)
        if token in tokens:
            raise ValueError(f"{field_name} must not contain duplicate labels: {label!r}")
        tokens.add(token)
        result.append(label)
    return result


def _validate_column_label(value: Any, *, field_name: str, frame_name: str | None) -> Any:
    prefix = f"Frame {frame_name!r} " if frame_name is not None else ""
    if isinstance(value, tuple):
        raise ValueError(
            f"{prefix}{field_name} contains tuple labels; pivot_frame requires flat labels"
        )
    if _is_empty_cell(value):
        raise ValueError(f"{prefix}{field_name} contains an empty pivot column label")
    return value


def _ensure_no_output_collisions(
    index_columns: list[str], pivot_columns: list[Any], *, output: str
) -> None:
    index_tokens = {_hashable_token(column, field_name="index_columns") for column in index_columns}
    collisions = [
        column
        for column in pivot_columns
        if _hashable_token(column, field_name="column_keys") in index_tokens
    ]
    if collisions:
        raise ValueError(
            f"Pivot output frame {output!r} would contain duplicate index/pivot columns: {collisions!r}"
        )


def _ensure_no_unexpected_pivot_keys(
    actual_values: Iterable[Any],
    configured_keys: list[Any],
    *,
    source: str,
    column_key: str,
) -> None:
    configured = {_hashable_token(key, field_name="column_keys") for key in configured_keys}
    unexpected: list[Any] = []
    seen: set[Any] = set()
    for value in actual_values:
        label = _validate_column_label(value, field_name=column_key, frame_name=source)
        token = _hashable_token(label, field_name=column_key)
        if token in configured or token in seen:
            continue
        seen.add(token)
        unexpected.append(label)
    if unexpected:
        raise ValueError(
            f"Frame {source!r} contains {column_key!r} value(s) not listed in "
            f"column_keys: {unexpected!r}"
        )


def _collect_cells(
    source: pd.DataFrame,
    *,
    index_columns: list[str],
    column_key: str,
    value_column: str,
) -> tuple[
    list[tuple[tuple[Any, ...], dict[str, Any]]],
    dict[tuple[tuple[Any, ...], Any], list[Any]],
    list[dict[str, Any]],
]:
    row_values: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    seen_rows: set[tuple[Any, ...]] = set()
    cell_values: dict[tuple[tuple[Any, ...], Any], list[Any]] = {}
    duplicate_cells: list[dict[str, Any]] = []

    for row_index, row in source.iterrows():
        row_token = tuple(
            _hashable_token(row[column], field_name=column) for column in index_columns
        )
        if row_token not in seen_rows:
            seen_rows.add(row_token)
            row_values.append(
                (
                    row_token,
                    {column: _plain_value(row[column]) for column in index_columns},
                )
            )

        pivot_label = _validate_column_label(
            row[column_key], field_name=column_key, frame_name=None
        )
        pivot_token = _hashable_token(pivot_label, field_name=column_key)
        cell_key = (row_token, pivot_token)
        values = cell_values.setdefault(cell_key, [])
        if values:
            duplicate_cells.append(
                {
                    "row_index": int(row_index) if isinstance(row_index, int) else row_index,
                    "index": {column: _plain_value(row[column]) for column in index_columns},
                    "column_key": _plain_value(pivot_label),
                }
            )
        values.append(row[value_column])

    return row_values, cell_values, duplicate_cells


def _aggregate_cell_values(
    values: list[Any],
    *,
    fill_value: Any,
    aggregation: str,
    separator: str,
) -> Any:
    if not values:
        return fill_value
    if len(values) == 1:
        return _plain_value(values[0])
    if aggregation == "first":
        for value in values:
            if not _is_empty_cell(value):
                return _plain_value(value)
        return ""
    texts = [_cell_text(value) for value in values if not _is_empty_cell(value)]
    return separator.join(texts) if texts else ""


def _plain_value(value: Any) -> Any:
    if _is_empty_cell(value):
        return ""
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            return value
    return value


def _cell_text(value: Any) -> str:
    plain = _plain_value(value)
    return "" if plain == "" else str(plain)


def _hashable_token(value: Any, *, field_name: str) -> Any:
    if _is_empty_cell(value):
        return None
    plain = _plain_value(value)
    try:
        hash(plain)
    except TypeError as exc:
        raise TypeError(f"{field_name} contains unhashable value {plain!r}") from exc
    return plain




def _duplicate_column_names(frame: pd.DataFrame) -> list[Any]:
    columns = list(frame.columns)
    return list(dict.fromkeys(column for column in columns if columns.count(column) > 1))


def _write_lifecycle(
    out: dict[str, Any],
    *,
    source: str,
    output: str,
    lifecycle: Mapping[str, Any] | None,
    step_name: str,
) -> None:
    if source != output:
        mark_source_if_unclassified(out, source)

    lifecycle_cfg = dict(lifecycle or {})
    role = str(lifecycle_cfg.get("role", "readonly_projection"))
    render = str(lifecycle_cfg.get("render", "visible_by_default"))
    canonical = bool(lifecycle_cfg.get("canonical", False))
    editable = lifecycle_cfg.get("editable", False)
    consistency_policy = lifecycle_cfg.get("consistency_policy")
    if consistency_policy is not None and not isinstance(consistency_policy, Mapping):
        raise TypeError("lifecycle.consistency_policy must be a mapping")

    write_frame_lifecycle(
        out,
        output,
        role=role,
        canonical=canonical,
        editable=editable,
        render=render,
        derived_from=[source],
        produced_by={"step": "pivot_frame", "name": step_name},
        consistency_policy=consistency_policy,
        preserve_existing_canonical=False,
    )
