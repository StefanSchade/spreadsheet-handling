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
    config_id = name or output
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
    previous_config = _xref_config(frames, config_id, matrix=matrix)
    dense_axes = (
        dict(previous_config["dense_axes"])
        if (
            isinstance(previous_config, Mapping)
            and isinstance(previous_config.get("dense_axes"), Mapping)
        )
        else None
    )
    payload = {
        "operation": "expand_xref",
        "matrix": matrix,
        "relation": output,
        "row_keys": list(row_key_cols),
        "column_keys": list(value_cols),
        "column_key": column_key,
        "value": value,
        "drop_empty": bool(drop_empty),
    }
    if dense_axes is not None:
        payload["dense_axes"] = dense_axes
    _write_xref_meta(
        out,
        config_id=config_id,
        payload=payload,
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
    dense_axes: Mapping[str, Any] | None = None,
    name: str | None = None,
) -> Frames:
    """Contract explicit long-form rows into a matrix/cross-table frame."""
    config_id = name or relation
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

    dense_config = _dense_axes_from_config_or_meta(
        frames,
        dense_axes=dense_axes,
        config_id=config_id,
        relation=relation,
    )
    dense_resolved = _resolve_dense_axes(
        frames,
        dense_config=dense_config,
        row_keys=row_key_cols,
        column_key=column_key,
    )
    matrix_cols = _matrix_column_keys(
        frames,
        relation=relation,
        config_id=config_id,
        column_key=column_key,
        explicit_column_keys=column_keys,
        dense_resolved=dense_resolved,
    )
    _ensure_flat_axis_labels(matrix_cols, "column_keys")
    row_identities = (
        dense_resolved["row_identities"]
        if "row_identities" in dense_resolved
        else _ordered_row_identities(source, row_key_cols)
    )
    _ensure_relation_within_dense_axes(
        source,
        row_keys=row_key_cols,
        column_key=column_key,
        dense_resolved=dense_resolved,
    )

    values_by_pair = {
        (
            _relation_row_identity(
                source_row,
                row_key_cols,
                normalize="row_identities" in dense_resolved,
            ),
            _relation_column_identity(
                source_row[column_key],
                normalize="column_keys" in dense_resolved,
            ),
        ): source_row[value]
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
    payload = {
        "operation": "contract_xref",
        "relation": relation,
        "matrix": output,
        "row_keys": list(row_key_cols),
        "column_keys": list(matrix_cols),
        "column_key": column_key,
        "value": value,
    }
    dense_payload = _dense_axes_meta_payload(
        dense_config=dense_config,
        dense_resolved=dense_resolved,
        row_keys=row_key_cols,
        column_keys=matrix_cols,
    )
    if dense_payload is not None:
        payload["dense_axes"] = dense_payload
    _write_xref_meta(
        out,
        config_id=config_id,
        payload=payload,
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


def _relation_row_identity(
    row: Any,
    row_keys: list[Any],
    *,
    normalize: bool,
) -> tuple[Any, ...]:
    if not normalize:
        return tuple(row[row_key] for row_key in row_keys)
    return tuple(_plain_axis_value(row[row_key]) for row_key in row_keys)


def _relation_column_identity(value: Any, *, normalize: bool) -> Any:
    if not normalize:
        return value
    return _plain_axis_value(value)


def _matrix_column_keys(
    frames: Mapping[str, Any],
    *,
    relation: str,
    config_id: str,
    column_key: str,
    explicit_column_keys: Iterable[Any] | None,
    dense_resolved: Mapping[str, Any],
) -> list[Any]:
    if explicit_column_keys is not None:
        configured = _as_list(explicit_column_keys, "column_keys")
        dense_columns = dense_resolved.get("column_keys")
        if dense_columns is not None and not _ordered_values_equal(configured, dense_columns):
            raise ValueError(
                "column_keys must match dense_axes.columns_from order when both are configured: "
                f"{configured!r} vs {list(dense_columns)!r}"
            )
        return configured
    if "column_keys" in dense_resolved:
        return list(dense_resolved["column_keys"])
    return _column_keys_from_meta_or_relation(
        frames,
        relation=relation,
        config_id=config_id,
        column_key=column_key,
    )


def _dense_axes_from_config_or_meta(
    frames: Mapping[str, Any],
    *,
    dense_axes: Mapping[str, Any] | None,
    config_id: str,
    relation: str,
) -> Mapping[str, Any] | None:
    if dense_axes is not None:
        if not isinstance(dense_axes, Mapping):
            raise TypeError("dense_axes must be a mapping")
        return dict(dense_axes)
    config = _xref_config(frames, config_id, relation=relation)
    if isinstance(config, Mapping) and isinstance(config.get("dense_axes"), Mapping):
        return dict(config["dense_axes"])
    return None


def _resolve_dense_axes(
    frames: Mapping[str, Any],
    *,
    dense_config: Mapping[str, Any] | None,
    row_keys: list[Any],
    column_key: str,
) -> dict[str, Any]:
    if dense_config is None:
        return {}
    if not isinstance(dense_config, Mapping):
        raise TypeError("dense_axes must be a mapping")

    unsupported = sorted(set(dense_config) - {"rows_from", "columns_from", "resolved"})
    if unsupported:
        raise ValueError(f"dense_axes contains unsupported key(s): {unsupported!r}")

    resolved: dict[str, Any] = {}
    stored_resolved = dense_config.get("resolved")
    stored = stored_resolved if isinstance(stored_resolved, Mapping) else {}

    if dense_config.get("rows_from") is not None:
        resolved["row_config"] = _axis_source_config(
            dense_config["rows_from"],
            field_name="dense_axes.rows_from",
            allow_multiple=True,
        )
        resolved["row_identities"] = _row_identities_from_axis_source(
            frames,
            config=resolved["row_config"],
            row_keys=row_keys,
            stored_resolved=stored,
        )
    elif isinstance(stored.get("row_identities"), list):
        resolved["row_identities"] = _stored_row_identities(stored["row_identities"], row_keys)

    if dense_config.get("columns_from") is not None:
        resolved["column_config"] = _axis_source_config(
            dense_config["columns_from"],
            field_name="dense_axes.columns_from",
            allow_multiple=False,
        )
        resolved["column_keys"] = _column_keys_from_axis_source(
            frames,
            config=resolved["column_config"],
            stored_resolved=stored,
        )
    elif isinstance(stored.get("column_keys"), list):
        resolved["column_keys"] = _stored_column_keys(stored["column_keys"])

    return resolved


def _axis_source_config(
    raw: Any,
    *,
    field_name: str,
    allow_multiple: bool,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{field_name} must be a mapping")

    unsupported = sorted(set(raw) - {"frame", "key", "keys"})
    if unsupported:
        raise ValueError(f"{field_name} contains unsupported key(s): {unsupported!r}")

    frame = raw.get("frame")
    if not isinstance(frame, str) or not frame.strip():
        raise ValueError(f"{field_name}.frame must be a non-empty string")

    if raw.get("key") is not None and raw.get("keys") is not None:
        raise ValueError(f"{field_name} must configure either key or keys, not both")
    if raw.get("key") is not None:
        keys = [raw["key"]]
    elif raw.get("keys") is not None:
        keys = _as_list(raw["keys"], f"{field_name}.keys")
    else:
        raise ValueError(f"{field_name} must configure key or keys explicitly")

    _ensure_flat_axis_labels(keys, f"{field_name}.key")
    if not allow_multiple and len(keys) != 1:
        raise ValueError(f"{field_name}.key must identify exactly one flat axis column")
    config: dict[str, Any] = {"frame": frame}
    if len(keys) == 1:
        config["key"] = keys[0]
    else:
        config["keys"] = list(keys)
    return config


def _axis_config_keys(config: Mapping[str, Any]) -> list[Any]:
    keys = config.get("keys")
    if isinstance(keys, list):
        return list(keys)
    key = config.get("key")
    if isinstance(key, list):
        return list(key)
    return [key]


def _row_identities_from_axis_source(
    frames: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    row_keys: list[Any],
    stored_resolved: Mapping[str, Any],
) -> list[tuple[Any, ...]]:
    source = _optional_axis_frame(frames, config)
    if source is None:
        stored = stored_resolved.get("row_identities")
        if isinstance(stored, list):
            return _stored_row_identities(stored, row_keys)
        raise KeyError(f"Dense row-axis frame {config['frame']!r} not found")

    axis_keys = _axis_config_keys(config)
    if len(axis_keys) != len(row_keys):
        raise ValueError(
            "dense_axes.rows_from key arity must match row_keys: "
            f"{axis_keys!r} vs {row_keys!r}"
        )
    _ensure_columns(source, axis_keys, frame_name=str(config["frame"]), field_name="dense row axis")

    identities: list[tuple[Any, ...]] = []
    seen: set[tuple[Any, ...]] = set()
    for row_number, (_, source_row) in enumerate(source.iterrows(), start=1):
        identity = tuple(_plain_axis_value(source_row[key]) for key in axis_keys)
        _ensure_non_empty_axis_identity(
            identity,
            frame_name=str(config["frame"]),
            field_name="dense row axis",
            row_number=row_number,
        )
        if identity in seen:
            raise ValueError(
                f"Dense row-axis frame {config['frame']!r} contains duplicate key {identity!r}"
            )
        seen.add(identity)
        identities.append(identity)
    return identities


def _column_keys_from_axis_source(
    frames: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    stored_resolved: Mapping[str, Any],
) -> list[Any]:
    source = _optional_axis_frame(frames, config)
    if source is None:
        stored = stored_resolved.get("column_keys")
        if isinstance(stored, list):
            return _stored_column_keys(stored)
        raise KeyError(f"Dense column-axis frame {config['frame']!r} not found")

    axis_keys = _axis_config_keys(config)
    key = axis_keys[0]
    _ensure_columns(source, [key], frame_name=str(config["frame"]), field_name="dense column axis")

    columns: list[Any] = []
    seen: set[Any] = set()
    for row_number, raw_value in enumerate(source[key].tolist(), start=1):
        value = _plain_axis_value(raw_value)
        _ensure_non_empty_axis_identity(
            (value,),
            frame_name=str(config["frame"]),
            field_name="dense column axis",
            row_number=row_number,
        )
        if value in seen:
            raise ValueError(
                f"Dense column-axis frame {config['frame']!r} contains duplicate key {value!r}"
            )
        seen.add(value)
        columns.append(value)
    return columns


def _ensure_relation_within_dense_axes(
    relation: pd.DataFrame,
    *,
    row_keys: list[Any],
    column_key: str,
    dense_resolved: Mapping[str, Any],
) -> None:
    if "row_identities" in dense_resolved:
        _ensure_relation_rows_within_dense_axis(
            relation,
            row_keys=row_keys,
            allowed_rows=list(dense_resolved["row_identities"]),
        )

    if "column_keys" in dense_resolved:
        _ensure_relation_columns_within_dense_axis(
            relation,
            column_key=column_key,
            allowed_columns=list(dense_resolved["column_keys"]),
        )


def _ensure_relation_rows_within_dense_axis(
    relation: pd.DataFrame,
    *,
    row_keys: list[Any],
    allowed_rows: list[tuple[Any, ...]],
) -> None:
    unknown_rows: list[dict[Any, Any]] = []
    for _, row in relation.iterrows():
        identity = tuple(_plain_axis_value(row[row_key]) for row_key in row_keys)
        if _tuple_in(identity, allowed_rows):
            continue
        unknown_rows.append({
            row_key: identity[index]
            for index, row_key in enumerate(row_keys)
        })
    if unknown_rows:
        raise ValueError(
            "Relation contains row identities outside dense_axes.rows_from: "
            f"{unknown_rows!r}"
        )


def _ensure_relation_columns_within_dense_axis(
    relation: pd.DataFrame,
    *,
    column_key: str,
    allowed_columns: list[Any],
) -> None:
    unknown_columns: list[Any] = []
    for raw_value in relation[column_key].tolist():
        value = _plain_axis_value(raw_value)
        if any(_values_equal(value, allowed) for allowed in allowed_columns):
            continue
        if not any(_values_equal(value, existing) for existing in unknown_columns):
            unknown_columns.append(value)
    if unknown_columns:
        raise ValueError(
            "Relation contains column identities outside dense_axes.columns_from: "
            f"{unknown_columns!r}"
        )


def _tuple_in(value: tuple[Any, ...], values: Iterable[tuple[Any, ...]]) -> bool:
    return any(_ordered_values_equal(value, existing) for existing in values)


def _optional_axis_frame(
    frames: Mapping[str, Any],
    config: Mapping[str, Any],
) -> pd.DataFrame | None:
    frame_name = str(config["frame"])
    if frame_name not in frames:
        return None
    return _require_frame(frames, frame_name)


def _stored_row_identities(raw: list[Any], row_keys: list[Any]) -> list[tuple[Any, ...]]:
    identities: list[tuple[Any, ...]] = []
    seen: set[tuple[Any, ...]] = set()
    for position, item in enumerate(raw, start=1):
        if isinstance(item, Mapping):
            missing = [row_key for row_key in row_keys if row_key not in item]
            if missing:
                raise KeyError(
                    f"Stored dense row identity #{position} is missing key(s): {missing!r}"
                )
            identity = tuple(item[row_key] for row_key in row_keys)
        elif len(row_keys) == 1:
            identity = (item,)
        else:
            raise TypeError("Stored dense row identities for composite row_keys must be mappings")
        if identity in seen:
            raise ValueError(f"Stored dense row identities contain duplicate key {identity!r}")
        seen.add(identity)
        identities.append(identity)
    return identities


def _stored_column_keys(raw: list[Any]) -> list[Any]:
    _ensure_flat_axis_labels(raw, "stored dense column_keys")
    columns: list[Any] = []
    for position, item in enumerate(raw, start=1):
        value = _plain_axis_value(item)
        _ensure_non_empty_axis_identity(
            (value,),
            frame_name="_meta",
            field_name="stored dense column axis",
            row_number=position,
        )
        if any(_values_equal(existing, value) for existing in columns):
            raise ValueError(f"Stored dense column_keys contain duplicate key {value!r}")
        columns.append(value)
    return columns


def _plain_axis_value(value: Any) -> Any:
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (AttributeError, ValueError, TypeError):
            pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _ensure_non_empty_axis_identity(
    identity: tuple[Any, ...],
    *,
    frame_name: str,
    field_name: str,
    row_number: int,
) -> None:
    if any(_is_empty_cell(value) for value in identity):
        raise ValueError(
            f"Frame {frame_name!r}, row {row_number}: {field_name} key must not be empty"
        )


def _dense_axes_meta_payload(
    *,
    dense_config: Mapping[str, Any] | None,
    dense_resolved: Mapping[str, Any],
    row_keys: list[Any],
    column_keys: list[Any],
) -> dict[str, Any] | None:
    if dense_config is None and not dense_resolved:
        return None

    payload: dict[str, Any] = {}
    if "row_config" in dense_resolved:
        payload["rows_from"] = dict(dense_resolved["row_config"])
    elif isinstance(dense_config, Mapping) and isinstance(dense_config.get("rows_from"), Mapping):
        payload["rows_from"] = dict(dense_config["rows_from"])

    if "column_config" in dense_resolved:
        payload["columns_from"] = dict(dense_resolved["column_config"])
    elif isinstance(dense_config, Mapping) and isinstance(
        dense_config.get("columns_from"),
        Mapping,
    ):
        payload["columns_from"] = dict(dense_config["columns_from"])

    resolved: dict[str, Any] = {}
    if "row_identities" in dense_resolved:
        resolved["row_identities"] = [
            {row_key: identity[index] for index, row_key in enumerate(row_keys)}
            for identity in dense_resolved["row_identities"]
        ]
    if "column_keys" in dense_resolved:
        resolved["column_keys"] = list(dense_resolved["column_keys"])
    elif payload.get("columns_from") is not None:
        resolved["column_keys"] = list(column_keys)

    if resolved:
        payload["resolved"] = resolved
    return payload if payload else None


def _values_equal(left: Any, right: Any) -> bool:
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _ordered_values_equal(left: Iterable[Any], right: Iterable[Any]) -> bool:
    left_values = list(left)
    right_values = list(right)
    return len(left_values) == len(right_values) and all(
        _values_equal(left_value, right_value)
        for left_value, right_value in zip(left_values, right_values, strict=True)
    )


def _column_keys_from_meta_or_relation(
    frames: Mapping[str, Any],
    *,
    relation: str,
    config_id: str,
    column_key: str,
) -> list[Any]:
    config = _xref_config(frames, config_id, relation=relation)
    if isinstance(config, Mapping) and isinstance(config.get("column_keys"), list):
        return list(config["column_keys"])
    source = _require_frame(frames, relation)
    return _ordered_unique(source[column_key].tolist())


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
