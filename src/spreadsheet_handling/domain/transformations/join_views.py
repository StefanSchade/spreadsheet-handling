"""Bounded declarative join view operations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.frame_lifecycle import (
    mark_source_if_unclassified,
    write_frame_lifecycle,
)

Frames = dict[str, Any]

_HOW_VALUES = {"left", "inner", "semi"}
_COLLISION_POLICIES = {"fail", "suffix"}
_WHERE_PREDICATES = {"equals", "in", "non_empty", "is_null", "not_null"}


def join_frames(
    frames: Mapping[str, Any],
    *,
    left: str,
    right: str,
    output: str,
    key: str | None = None,
    keys: Iterable[str] | None = None,
    left_key: str | None = None,
    right_key: str | None = None,
    left_keys: Iterable[str] | None = None,
    right_keys: Iterable[str] | None = None,
    how: str = "left",
    left_columns: Iterable[str] | None = None,
    right_columns: Iterable[str] | None = None,
    left_rename: Mapping[str, str] | None = None,
    right_rename: Mapping[str, str] | None = None,
    collisions: str = "fail",
    suffixes: Iterable[str] = ("_left", "_right"),
    right_where: Mapping[str, Any] | None = None,
    where: Mapping[str, Any] | None = None,
    right_unique: bool | None = None,
    lifecycle: Mapping[str, Any] | None = None,
    name: str | None = None,
) -> Frames:
    """Join two frames into an explicit materialized view frame."""
    if how not in _HOW_VALUES:
        raise ValueError(f"how must be one of {sorted(_HOW_VALUES)!r}; got {how!r}")
    if collisions not in _COLLISION_POLICIES:
        raise ValueError(
            f"collisions must be one of {sorted(_COLLISION_POLICIES)!r}; got {collisions!r}"
        )

    left_df = _require_frame(frames, left)
    right_df = _apply_where(_require_frame(frames, right), right_where, frame_name=right)
    left_join_keys, right_join_keys = _resolve_join_keys(
        key=key,
        keys=keys,
        left_key=left_key,
        right_key=right_key,
        left_keys=left_keys,
        right_keys=right_keys,
    )
    _ensure_columns(left_df, left_join_keys, frame_name=left, field_name="join key")
    _ensure_columns(right_df, right_join_keys, frame_name=right, field_name="join key")

    should_check_right_unique = right_unique if right_unique is not None else how != "semi"
    if should_check_right_unique:
        _ensure_unique_keys(right_df, right_join_keys, frame_name=right)

    left_selected = (
        _string_list(left_columns, "left_columns")
        if left_columns is not None
        else list(left_df.columns)
    )
    right_selected = (
        _string_list(right_columns, "right_columns")
        if right_columns is not None
        else ([] if how == "semi" else _default_right_columns(right_df, right_join_keys))
    )
    _ensure_columns(left_df, left_selected, frame_name=left, field_name="left_columns")
    _ensure_columns(right_df, right_selected, frame_name=right, field_name="right_columns")

    temp_keys = _temp_join_key_columns(left_df, right_df, output, count=len(left_join_keys))
    left_work, left_outputs = _side_work_frame(
        left_df,
        side_name=left,
        selected_columns=left_selected,
        join_keys=left_join_keys,
        temp_keys=temp_keys,
        rename=left_rename,
        prefix="left",
    )
    right_work, right_outputs = _side_work_frame(
        right_df,
        side_name=right,
        selected_columns=right_selected,
        join_keys=right_join_keys,
        temp_keys=temp_keys,
        rename=right_rename,
        prefix="right",
    )

    left_outputs, right_outputs = _resolve_output_collisions(
        left_work,
        right_work,
        left_outputs,
        right_outputs,
        collisions=collisions,
        suffixes=suffixes,
        output=output,
    )
    left_work = _rename_side_outputs(left_work, left_outputs)
    right_work = _rename_side_outputs(right_work, right_outputs)

    if how == "semi":
        result = _semi_join(left_work, right_work, temp_keys=temp_keys, where=where, output=output)
        output_columns = [spec.output for spec in left_outputs]
    else:
        merged = left_work.merge(
            right_work,
            on=temp_keys,
            how=how,
            sort=False,
            validate=None if not should_check_right_unique else "m:1",
        )
        filtered = _apply_where(merged, where, frame_name=output)
        output_columns = [spec.output for spec in [*left_outputs, *right_outputs]]
        result = filtered.loc[:, output_columns].copy()

    result = result.reset_index(drop=True)
    result = result.where(pd.notnull(result), "")
    out: dict[str, Any] = dict(frames)
    out[output] = result
    _write_lifecycle(
        out,
        left=left,
        right=right,
        output=output,
        lifecycle=lifecycle,
        step_name=name or "join_frames",
    )
    return out


@dataclass
class _ColumnSpec:
    original: str
    output: str


def _resolve_join_keys(
    *,
    key: str | None,
    keys: Iterable[str] | None,
    left_key: str | None,
    right_key: str | None,
    left_keys: Iterable[str] | None,
    right_keys: Iterable[str] | None,
) -> tuple[list[str], list[str]]:
    same_key_configs = [value is not None for value in (key, keys)].count(True)
    paired_singular = left_key is not None or right_key is not None
    paired_plural = left_keys is not None or right_keys is not None
    paired_configs = [paired_singular, paired_plural].count(True)
    if same_key_configs + paired_configs != 1:
        raise ValueError(
            "Configure join keys with exactly one of `key`, `keys`, "
            "`left_key`/`right_key`, or `left_keys`/`right_keys`"
        )

    if key is not None:
        _ensure_string(key, "key")
        return [key], [key]
    if keys is not None:
        resolved = _string_list(keys, "keys")
        return resolved, resolved
    if paired_singular:
        if left_key is None or right_key is None:
            raise ValueError("left_key and right_key must be configured together")
        _ensure_string(left_key, "left_key")
        _ensure_string(right_key, "right_key")
        return [left_key], [right_key]
    if left_keys is None or right_keys is None:
        raise ValueError("left_keys and right_keys must be configured together")
    left_resolved = _string_list(left_keys, "left_keys")
    right_resolved = _string_list(right_keys, "right_keys")
    if len(left_resolved) != len(right_resolved):
        raise ValueError("left_keys and right_keys must have the same length")
    return left_resolved, right_resolved


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Frame {name!r} not found")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Frame {name!r} must be a pandas DataFrame")
    if isinstance(frame.columns, pd.MultiIndex) or any(
        isinstance(column, tuple) for column in frame.columns
    ):
        raise ValueError(f"Frame {name!r} must have flat columns")
    duplicates = _duplicate_column_names(frame)
    if duplicates:
        raise ValueError(f"Frame {name!r} must not contain duplicate columns: {duplicates!r}")
    return frame


def _default_right_columns(right_df: pd.DataFrame, right_join_keys: list[str]) -> list[str]:
    key_set = set(right_join_keys)
    return [column for column in right_df.columns if column not in key_set]


def _side_work_frame(
    source: pd.DataFrame,
    *,
    side_name: str,
    selected_columns: list[str],
    join_keys: list[str],
    temp_keys: list[str],
    rename: Mapping[str, str] | None,
    prefix: str,
) -> tuple[pd.DataFrame, list[_ColumnSpec]]:
    rename_map = _rename_map(rename, selected_columns, side_name=side_name, prefix=prefix)
    carry_columns = list(dict.fromkeys([*join_keys, *selected_columns]))
    work = source.loc[:, carry_columns].copy()
    for index, join_key in enumerate(join_keys):
        work[temp_keys[index]] = [_join_token(value) for value in source[join_key].tolist()]

    output_specs = [
        _ColumnSpec(original=column, output=rename_map.get(column, column))
        for column in selected_columns
    ]
    output_names = [spec.output for spec in output_specs]
    duplicates = [
        name
        for name in dict.fromkeys(name for name in output_names if output_names.count(name) > 1)
    ]
    if duplicates:
        raise ValueError(f"{prefix}_rename creates duplicate output column(s): {duplicates!r}")

    keep_columns = [*temp_keys, *selected_columns]
    return work.loc[:, keep_columns].copy(), output_specs


def _rename_map(
    rename: Mapping[str, str] | None,
    selected_columns: list[str],
    *,
    side_name: str,
    prefix: str,
) -> dict[str, str]:
    if rename is None:
        return {}
    if not isinstance(rename, Mapping):
        raise TypeError(f"{prefix}_rename must be a mapping")
    selected = set(selected_columns)
    resolved: dict[str, str] = {}
    for old, new in rename.items():
        if (
            not isinstance(old, str)
            or not old.strip()
            or not isinstance(new, str)
            or not new.strip()
        ):
            raise ValueError(f"{prefix}_rename entries must map non-empty string column names")
        if old not in selected:
            raise KeyError(
                f"{prefix}_rename references column {old!r}, but it is not selected "
                f"from frame {side_name!r}"
            )
        resolved[old] = new
    return resolved


def _resolve_output_collisions(
    left_work: pd.DataFrame,
    right_work: pd.DataFrame,
    left_outputs: list[_ColumnSpec],
    right_outputs: list[_ColumnSpec],
    *,
    collisions: str,
    suffixes: Iterable[str],
    output: str,
) -> tuple[list[_ColumnSpec], list[_ColumnSpec]]:
    left_names = [spec.output for spec in left_outputs]
    right_names = [spec.output for spec in right_outputs]
    overlap = sorted(set(left_names) & set(right_names))
    if not overlap:
        return left_outputs, right_outputs
    if collisions == "fail":
        raise ValueError(
            f"Join output frame {output!r} has colliding column name(s) {overlap!r}; "
            "configure left_rename/right_rename or set collisions='suffix'"
        )

    left_suffix, right_suffix = _suffix_pair(suffixes)
    for spec in left_outputs:
        if spec.output in overlap:
            spec.output = f"{spec.output}{left_suffix}"
    for spec in right_outputs:
        if spec.output in overlap:
            spec.output = f"{spec.output}{right_suffix}"

    renamed = [spec.output for spec in [*left_outputs, *right_outputs]]
    duplicates = [
        name for name in dict.fromkeys(name for name in renamed if renamed.count(name) > 1)
    ]
    if duplicates:
        raise ValueError(
            f"Suffix collision handling still creates duplicate output column(s): {duplicates!r}"
        )
    _ensure_output_columns_exist(left_work, [spec.original for spec in left_outputs], side="left")
    _ensure_output_columns_exist(
        right_work, [spec.original for spec in right_outputs], side="right"
    )
    return left_outputs, right_outputs


def _rename_side_outputs(frame: pd.DataFrame, specs: list[_ColumnSpec]) -> pd.DataFrame:
    rename = {spec.original: spec.output for spec in specs if spec.original != spec.output}
    return frame.rename(columns=rename)


def _semi_join(
    left_work: pd.DataFrame,
    right_work: pd.DataFrame,
    *,
    temp_keys: list[str],
    where: Mapping[str, Any] | None,
    output: str,
) -> pd.DataFrame:
    row_id = _temp_column("__join_frames_left_row", left_work, right_work)
    left_numbered = left_work.copy()
    left_numbered[row_id] = range(len(left_numbered))
    candidate = left_numbered.merge(right_work, on=temp_keys, how="inner", sort=False)
    filtered = _apply_where(candidate, where, frame_name=output)
    keep_ids = set(filtered[row_id].tolist())
    result = left_numbered.loc[left_numbered[row_id].isin(keep_ids)].copy()
    return result.drop(columns=[row_id, *temp_keys])


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
            "where must configure exactly one predicate among " f"{sorted(_WHERE_PREDICATES)!r}"
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


def _ensure_unique_keys(frame: pd.DataFrame, keys: list[str], *, frame_name: str) -> None:
    duplicate_mask = frame.duplicated(subset=keys, keep=False)
    if duplicate_mask.any():
        duplicates = frame.loc[duplicate_mask, keys].to_dict(orient="records")
        raise ValueError(
            f"Right frame {frame_name!r} contains duplicate join key(s) on {keys!r}: "
            f"{duplicates[:5]!r}"
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


def _string_list(value: Iterable[str], field_name: str) -> list[str]:
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


def _suffix_pair(suffixes: Iterable[str]) -> tuple[str, str]:
    if isinstance(suffixes, (str, bytes)):
        raise TypeError("suffixes must be a two-item list, not a scalar")
    resolved = list(suffixes)
    if len(resolved) != 2:
        raise ValueError("suffixes must contain exactly two entries")
    left_suffix, right_suffix = resolved
    if not isinstance(left_suffix, str) or not isinstance(right_suffix, str):
        raise TypeError("suffixes entries must be strings")
    if left_suffix == right_suffix:
        raise ValueError("suffixes entries must differ")
    return left_suffix, right_suffix


def _ensure_output_columns_exist(frame: pd.DataFrame, columns: Iterable[str], *, side: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise AssertionError(f"{side} output column(s) vanished before join: {missing!r}")


def _temp_join_key_columns(
    left: pd.DataFrame,
    right: pd.DataFrame,
    output: str,
    *,
    count: int,
) -> list[str]:
    index = 0
    used = {*left.columns, *right.columns}
    names: list[str] = []
    while len(names) < count:
        candidate = f"__join_frames_{output}_{index}"
        index += 1
        if candidate in used:
            continue
        names.append(candidate)
    return names


def _temp_column(base: str, *frames: pd.DataFrame) -> str:
    used = {column for frame in frames for column in frame.columns}
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _join_token(value: Any) -> Any:
    if _is_empty_cell(value):
        return object()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    try:
        hash(value)
    except TypeError as exc:
        raise TypeError(f"Join key contains unhashable value {value!r}") from exc
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


def _duplicate_column_names(frame: pd.DataFrame) -> list[Any]:
    columns = list(frame.columns)
    return list(dict.fromkeys(column for column in columns if columns.count(column) > 1))


def _ensure_boolean_predicate(value: Any, predicate: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"where.{predicate} must be true or false")


def _write_lifecycle(
    out: dict[str, Any],
    *,
    left: str,
    right: str,
    output: str,
    lifecycle: Mapping[str, Any] | None,
    step_name: str,
) -> None:
    if left != output:
        mark_source_if_unclassified(out, left)
    if right != output:
        mark_source_if_unclassified(out, right)

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
        derived_from=[left, right],
        produced_by={"step": "join_frames", "name": step_name},
        consistency_policy=consistency_policy,
        preserve_existing_canonical=False,
    )
