"""Declarative single-frame extraction and filtering."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.frame_lifecycle import (
    mark_source_if_unclassified,
    write_frame_lifecycle,
)

Frames = dict[str, Any]

_WHERE_PREDICATES = {"equals", "in", "non_empty", "is_null", "not_null"}


def extract_frame(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    columns: Iterable[str] | None = None,
    where: Mapping[str, Any] | None = None,
    rename: Mapping[str, str] | None = None,
    constants: Mapping[str, Any] | None = None,
    sort_by: str | Iterable[str] | None = None,
    lifecycle: Mapping[str, Any] | None = None,
    name: str | None = None,
) -> Frames:
    """Extract a filtered, ordered projection from one source frame."""
    source_df = _require_frame(frames, source)
    projection = _project_columns(
        _apply_where(source_df, where, frame_name=source),
        columns=columns,
        frame_name=source,
    )

    if rename:
        projection = _rename_columns(projection, rename, output=output)
    if constants:
        projection = _add_constants(projection, constants, output=output)

    sort_columns = _string_list(sort_by, "sort_by") if sort_by is not None else []
    if sort_columns:
        _ensure_columns(projection, sort_columns, frame_name=output, field_name="sort_by")
        projection = projection.sort_values(sort_columns, kind="mergesort", na_position="last")

    result = projection.reset_index(drop=True)
    result = result.where(pd.notnull(result), "")

    out: dict[str, Any] = dict(frames)
    out[output] = result
    _write_lifecycle(
        out,
        source=source,
        output=output,
        lifecycle=lifecycle,
        step_name=name or "extract_frame",
    )
    return out


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Frame {name!r} not found")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Frame {name!r} must be a pandas DataFrame")
    if isinstance(frame.columns, pd.MultiIndex) or any(isinstance(col, tuple) for col in frame.columns):
        raise ValueError(f"Frame {name!r} must have flat columns")
    if len(set(frame.columns)) != len(frame.columns):
        raise ValueError(f"Frame {name!r} must not contain duplicate columns")
    return frame


def _project_columns(
    source: pd.DataFrame,
    *,
    columns: Iterable[str] | None,
    frame_name: str,
) -> pd.DataFrame:
    if columns is None:
        return source.copy()

    selected = _string_list(columns, "columns")
    _ensure_columns(source, selected, frame_name=frame_name, field_name="columns")
    return source.loc[:, selected].copy()


def _apply_where(
    source: pd.DataFrame,
    where: Mapping[str, Any] | None,
    *,
    frame_name: str,
) -> pd.DataFrame:
    if where is None:
        return source.copy()
    if not isinstance(where, Mapping):
        raise TypeError("where must be a mapping with `column` plus one supported predicate")

    column = where.get("column")
    if not isinstance(column, str) or not column.strip():
        raise ValueError("where.column must be a non-empty string")
    _ensure_columns(source, [column], frame_name=frame_name, field_name="where")

    predicates = [key for key in where if key in _WHERE_PREDICATES]
    unsupported = [key for key in where if key not in {*_WHERE_PREDICATES, "column"}]
    if unsupported:
        raise ValueError(
            f"Unsupported where predicate(s) {unsupported!r}; "
            f"supported predicates are {sorted(_WHERE_PREDICATES)!r}"
        )
    if len(predicates) != 1:
        raise ValueError(
            "where must configure exactly one predicate among "
            f"{sorted(_WHERE_PREDICATES)!r}"
        )

    predicate = predicates[0]
    values = source[column]
    if predicate == "equals":
        mask = values == where[predicate]
    elif predicate == "in":
        members = where[predicate]
        if isinstance(members, (str, bytes)) or not isinstance(members, Iterable):
            raise TypeError("where.in must be a list of allowed values, not a scalar")
        mask = values.isin(list(members))
    elif predicate == "non_empty":
        _ensure_boolean_predicate(where[predicate], predicate)
        mask = values.map(lambda value: not _is_empty_cell(value))
        if where[predicate] is False:
            mask = ~mask
    elif predicate == "is_null":
        _ensure_boolean_predicate(where[predicate], predicate)
        mask = values.isnull()
        if where[predicate] is False:
            mask = ~mask
    elif predicate == "not_null":
        _ensure_boolean_predicate(where[predicate], predicate)
        mask = values.notnull()
        if where[predicate] is False:
            mask = ~mask
    else:  # pragma: no cover - guarded above
        raise AssertionError(predicate)

    return source.loc[mask].copy()


def _rename_columns(
    source: pd.DataFrame,
    rename: Mapping[str, str],
    *,
    output: str,
) -> pd.DataFrame:
    if not isinstance(rename, Mapping):
        raise TypeError("rename must be a mapping of existing column name to output column name")
    rename_map: dict[str, str] = {}
    for old, new in rename.items():
        if not isinstance(old, str) or not isinstance(new, str) or not old.strip() or not new.strip():
            raise ValueError("rename entries must map non-empty string column names")
        rename_map[old] = new
    _ensure_columns(source, rename_map.keys(), frame_name=output, field_name="rename")

    renamed = source.rename(columns=rename_map)
    duplicates = _duplicate_column_names(renamed)
    if duplicates:
        raise ValueError(f"rename creates duplicate output column(s): {duplicates!r}")
    return renamed


def _add_constants(
    source: pd.DataFrame,
    constants: Mapping[str, Any],
    *,
    output: str,
) -> pd.DataFrame:
    if not isinstance(constants, Mapping):
        raise TypeError("constants must be a mapping of output column names to scalar values")

    result = source.copy()
    for column, value in constants.items():
        if not isinstance(column, str) or not column.strip():
            raise ValueError("constant column names must be non-empty strings")
        if column in result.columns:
            raise ValueError(
                f"constant column {column!r} already exists in output frame {output!r}"
            )
        if _is_non_scalar_constant(value):
            raise TypeError(f"constant column {column!r} must use a scalar value")
        result[column] = value
    return result


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
        produced_by={"step": "extract_frame", "name": step_name},
        consistency_policy=consistency_policy,
        preserve_existing_canonical=False,
    )


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


def _duplicate_column_names(frame: pd.DataFrame) -> list[str]:
    columns = list(frame.columns)
    return list(dict.fromkeys(column for column in columns if columns.count(column) > 1))


def _ensure_boolean_predicate(value: Any, predicate: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"where.{predicate} must be true or false")


def _is_empty_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_non_scalar_constant(value: Any) -> bool:
    if isinstance(value, (str, bytes)) or value is None:
        return False
    if isinstance(value, Mapping):
        return True
    if isinstance(value, Iterable) and not hasattr(value, "item"):
        return True
    return False
