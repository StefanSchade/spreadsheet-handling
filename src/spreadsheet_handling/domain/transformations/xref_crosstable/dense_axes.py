"""Dense-axis helpers for ``xref_crosstable``.

Package-internal split of the original flat module. Consumers reach the
public surface via ``spreadsheet_handling.domain.transformations.xref_crosstable``
and must not import from here directly.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain._cell_primitives import _is_empty_cell, _values_equal

from .primitives import (
    _as_list,
    _ensure_columns,
    _ensure_flat_axis_labels,
    _ordered_values_equal,
    _require_frame,
    _xref_config,
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
