"""Cross-table / XRef transformations.

This module owns the generic matrix <-> relation conversion used by the first
compact-transform slice.  It deliberately treats cell values as opaque.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

Frames = dict[str, Any]

_META_KEY = "xref_crosstable"


def expand_xref(
    frames: Mapping[str, Any],
    *,
    matrix: str,
    output: str,
    row_keys: str | Iterable[Any],
    value_columns: Iterable[Any] | None = None,
    column_key: str = "column_key",
    value: str = "value",
    drop_empty: bool = False,
    name: str | None = None,
) -> Frames:
    """Expand a matrix/cross-table frame into explicit long-form rows."""
    source = _require_frame(frames, matrix)
    row_key_cols = _as_list(row_keys, "row_keys")
    _ensure_flat_axis_labels(row_key_cols, "row_keys")
    _ensure_columns(source, row_key_cols, frame_name=matrix, field_name="row_keys")
    _ensure_output_names_do_not_collide(row_key_cols, column_key=column_key, value=value)

    value_cols = (
        _as_list(value_columns, "value_columns")
        if value_columns is not None
        else [col for col in source.columns if col not in row_key_cols]
    )
    _ensure_flat_axis_labels(value_cols, "value_columns")
    _ensure_columns(source, value_cols, frame_name=matrix, field_name="value_columns")

    records: list[dict[Any, Any]] = []
    for _, source_row in source.iterrows():
        row_identity = {row_key: source_row[row_key] for row_key in row_key_cols}
        for matrix_col in value_cols:
            cell_value = source_row[matrix_col]
            if drop_empty and _is_empty_cell(cell_value):
                continue
            records.append({
                **row_identity,
                column_key: matrix_col,
                value: cell_value,
            })

    relation = pd.DataFrame(records, columns=[*row_key_cols, column_key, value])
    out: dict[str, Any] = dict(frames)
    out[output] = relation
    _write_xref_meta(
        out,
        config_id=name or output,
        payload={
            "operation": "expand_xref",
            "matrix": matrix,
            "relation": output,
            "row_keys": list(row_key_cols),
            "column_keys": list(value_cols),
            "column_key": column_key,
            "value": value,
            "drop_empty": bool(drop_empty),
        },
    )
    return out


def contract_xref(
    frames: Mapping[str, Any],
    *,
    relation: str,
    output: str,
    row_keys: str | Iterable[Any],
    column_key: str = "column_key",
    value: str = "value",
    column_keys: Iterable[Any] | None = None,
    fill_value: Any = "",
    name: str | None = None,
) -> Frames:
    """Contract explicit long-form rows into a matrix/cross-table frame."""
    source = _require_frame(frames, relation)
    row_key_cols = _as_list(row_keys, "row_keys")
    _ensure_flat_axis_labels(row_key_cols, "row_keys")
    _ensure_columns(
        source,
        [*row_key_cols, column_key, value],
        frame_name=relation,
        field_name="row_keys/column_key/value",
    )
    _ensure_output_names_do_not_collide(row_key_cols, column_key=column_key, value=value)
    _ensure_unique_pairs(source, row_key_cols, column_key)

    matrix_cols = (
        _as_list(column_keys, "column_keys")
        if column_keys is not None
        else _column_keys_from_meta_or_relation(
            frames,
            relation=relation,
            config_id=name or relation,
            column_key=column_key,
        )
    )
    _ensure_flat_axis_labels(matrix_cols, "column_keys")
    row_identities = _ordered_row_identities(source, row_key_cols)

    values_by_pair = {
        (tuple(source_row[row_key] for row_key in row_key_cols), source_row[column_key]): source_row[value]
        for _, source_row in source.iterrows()
    }

    rows: list[dict[Any, Any]] = []
    for row_identity in row_identities:
        record = {
            row_key: row_identity[index]
            for index, row_key in enumerate(row_key_cols)
        }
        for matrix_col in matrix_cols:
            record[matrix_col] = values_by_pair.get((row_identity, matrix_col), fill_value)
        rows.append(record)

    matrix_frame = pd.DataFrame(rows, columns=[*row_key_cols, *matrix_cols])
    out: dict[str, Any] = dict(frames)
    out[output] = matrix_frame
    _write_xref_meta(
        out,
        config_id=name or relation,
        payload={
            "operation": "contract_xref",
            "relation": relation,
            "matrix": output,
            "row_keys": list(row_key_cols),
            "column_keys": list(matrix_cols),
            "column_key": column_key,
            "value": value,
        },
    )
    return out


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
    if isinstance(frame.columns, pd.MultiIndex) or any(isinstance(col, tuple) for col in frame.columns):
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


def _ensure_output_names_do_not_collide(
    row_keys: list[Any],
    *,
    column_key: str,
    value: str,
) -> None:
    reserved = {column_key, value}
    collisions = [row_key for row_key in row_keys if row_key in reserved]
    if collisions:
        raise ValueError(f"row_keys collide with output column names: {collisions!r}")
    if column_key == value:
        raise ValueError("column_key and value output names must differ")


def _is_empty_cell(cell_value: Any) -> bool:
    if cell_value is None:
        return True
    if isinstance(cell_value, str):
        return cell_value == ""
    try:
        return bool(pd.isna(cell_value))
    except (TypeError, ValueError):
        return False


def _ensure_unique_pairs(
    relation: pd.DataFrame,
    row_keys: list[Any],
    column_key: str,
) -> None:
    pair_cols = [*row_keys, column_key]
    duplicates = relation.duplicated(subset=pair_cols, keep=False)
    if duplicates.any():
        duplicate_rows = relation.loc[duplicates, pair_cols].to_dict(orient="records")
        raise ValueError(f"Duplicate xref row/column pairs: {duplicate_rows!r}")


def _ordered_row_identities(relation: pd.DataFrame, row_keys: list[Any]) -> list[tuple[Any, ...]]:
    seen: set[tuple[Any, ...]] = set()
    ordered: list[tuple[Any, ...]] = []
    for _, row in relation.iterrows():
        identity = tuple(row[row_key] for row_key in row_keys)
        if identity in seen:
            continue
        seen.add(identity)
        ordered.append(identity)
    return ordered


def _ordered_unique(values: Iterable[Any]) -> list[Any]:
    ordered: list[Any] = []
    for value in values:
        if any(_values_equal(existing, value) for existing in ordered):
            continue
        ordered.append(value)
    return ordered


def _values_equal(left: Any, right: Any) -> bool:
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _column_keys_from_meta_or_relation(
    frames: Mapping[str, Any],
    *,
    relation: str,
    config_id: str,
    column_key: str,
) -> list[Any]:
    meta = frames.get("_meta")
    if isinstance(meta, dict):
        configs = meta.get(_META_KEY)
        if isinstance(configs, dict):
            config = configs.get(config_id) or configs.get(relation)
            if isinstance(config, dict) and isinstance(config.get("column_keys"), list):
                return list(config["column_keys"])
    source = _require_frame(frames, relation)
    return _ordered_unique(source[column_key].tolist())


def _write_xref_meta(
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
