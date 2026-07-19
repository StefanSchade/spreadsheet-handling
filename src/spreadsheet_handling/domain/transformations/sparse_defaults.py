"""Sparse default-value collapse and expansion for editable crosstables."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
import warnings

import pandas as pd

Frames = dict[str, Any]

_META_KEY = "sparse_defaults"
_XREF_META_KEY = "xref_crosstable"
_MISSING = object()
_CONFLICT_POLICIES = {"error", "warn", "ignore"}


def sparse_collapse(
    frames: Mapping[str, Any],
    *,
    frame: str,
    default_value: Any,
    blank_value: Any = "",
    columns: Iterable[Any] | None = None,
    on_conflict: str = "error",
    name: str | None = None,
) -> Frames:
    """Replace configured default values in a frame with a sparse blank value."""
    source = _require_frame(frames, frame)
    target_columns = _target_columns_for_collapse(
        frames,
        source=source,
        frame=frame,
        columns=columns,
        config_id=name or frame,
    )
    _ensure_conflict_policy(on_conflict)
    _handle_blank_conflicts(
        source,
        frame=frame,
        columns=target_columns,
        default_value=default_value,
        blank_value=blank_value,
        on_conflict=on_conflict,
    )

    sparse = source.copy()
    for column in target_columns:
        sparse[column] = [
            blank_value if _values_equal(value, default_value) else value
            for value in sparse[column].tolist()
        ]

    out: dict[str, Any] = dict(frames)
    out[frame] = sparse
    _write_sparse_meta(
        out,
        config_id=name or frame,
        payload={
            "operation": "sparse_collapse",
            "frame": frame,
            "columns": list(target_columns),
            "default_value": default_value,
            "blank_value": blank_value,
            "on_conflict": on_conflict,
        },
    )
    return out


def sparse_expand(
    frames: Mapping[str, Any],
    *,
    frame: str,
    default_value: Any = _MISSING,
    blank_value: Any = _MISSING,
    columns: Iterable[Any] | None = None,
    name: str | None = None,
) -> Frames:
    """Fill sparse blank values in a frame with the configured default value."""
    source = _require_frame(frames, frame)
    config_id = name or frame
    meta = _sparse_meta(frames, config_id)
    resolved_default = _resolved_default_value(default_value, meta, config_id)
    resolved_blank = _resolved_blank_value(blank_value, meta)
    target_columns = _target_columns_for_expand(
        source,
        frame=frame,
        columns=columns,
        meta=meta,
    )

    dense = source.copy()
    for column in target_columns:
        dense[column] = [
            resolved_default if _is_blank_value(value, resolved_blank) else value
            for value in dense[column].tolist()
        ]

    out: dict[str, Any] = dict(frames)
    out[frame] = dense
    _write_sparse_meta(
        out,
        config_id=config_id,
        payload={
            "operation": "sparse_expand",
            "frame": frame,
            "columns": list(target_columns),
            "default_value": resolved_default,
            "blank_value": resolved_blank,
        },
    )
    return out


def _target_columns_for_collapse(
    frames: Mapping[str, Any],
    *,
    source: pd.DataFrame,
    frame: str,
    columns: Iterable[Any] | None,
    config_id: str,
) -> list[Any]:
    if columns is not None:
        target_columns = _as_column_list(columns, "columns")
    else:
        target_columns = _xref_column_keys_for_frame(frames, frame=frame, config_id=config_id)
        if target_columns is None:
            raise ValueError(
                "sparse_collapse requires explicit columns when no unambiguous "
                f"xref_crosstable metadata exists for frame {frame!r}"
            )
    _ensure_columns(source, target_columns, frame_name=frame)
    return target_columns


def _target_columns_for_expand(
    source: pd.DataFrame,
    *,
    frame: str,
    columns: Iterable[Any] | None,
    meta: Mapping[str, Any] | None,
) -> list[Any]:
    if columns is not None:
        target_columns = _as_column_list(columns, "columns")
    elif isinstance(meta, Mapping) and isinstance(meta.get("columns"), list):
        target_columns = list(meta["columns"])
    else:
        raise ValueError(
            "sparse_expand requires explicit columns when no sparse_defaults "
            f"metadata exists for frame {frame!r}"
        )
    _ensure_columns(source, target_columns, frame_name=frame)
    return target_columns


def _handle_blank_conflicts(
    source: pd.DataFrame,
    *,
    frame: str,
    columns: list[Any],
    default_value: Any,
    blank_value: Any,
    on_conflict: str,
) -> None:
    if on_conflict == "ignore":
        return

    conflicts: list[dict[str, Any]] = []
    for row_index, row in enumerate(source[columns].itertuples(index=False, name=None)):
        for column, value in zip(columns, row):
            if _is_blank_value(value, blank_value) and not _values_equal(value, default_value):
                conflicts.append({"row": row_index, "column": column})

    if not conflicts:
        return

    message = (
        f"Frame {frame!r} contains blank cells in sparse target columns before "
        f"collapse: {conflicts!r}. These cells would expand to the configured default."
    )
    if on_conflict == "error":
        raise ValueError(message)
    warnings.warn(message, UserWarning, stacklevel=2)


def _resolved_default_value(
    explicit_default: Any,
    meta: Mapping[str, Any] | None,
    config_id: str,
) -> Any:
    if explicit_default is not _MISSING:
        return explicit_default
    if isinstance(meta, Mapping) and "default_value" in meta:
        return meta["default_value"]
    raise ValueError(
        f"default_value is required for sparse_expand when no sparse_defaults "
        f"metadata exists for {config_id!r}"
    )


def _resolved_blank_value(explicit_blank: Any, meta: Mapping[str, Any] | None) -> Any:
    if explicit_blank is not _MISSING:
        return explicit_blank
    if isinstance(meta, Mapping) and "blank_value" in meta:
        return meta["blank_value"]
    return ""


def _as_column_list(value: Iterable[Any], field_name: str) -> list[Any]:
    if isinstance(value, (str, bytes)):
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
        isinstance(column, tuple) for column in frame.columns
    ):
        raise ValueError(f"Frame {name!r} must have flat columns")
    if len(set(frame.columns)) != len(frame.columns):
        raise ValueError(f"Frame {name!r} must not contain duplicate columns")
    return frame


def _ensure_columns(df: pd.DataFrame, columns: Iterable[Any], *, frame_name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"Frame {frame_name!r} is missing configured columns: {missing!r}")


def _ensure_conflict_policy(on_conflict: str) -> None:
    if on_conflict not in _CONFLICT_POLICIES:
        raise ValueError(f"on_conflict must be one of {sorted(_CONFLICT_POLICIES)!r}")


def _is_blank_value(value: Any, blank_value: Any) -> bool:
    if _is_blank_cell(blank_value):
        return _is_blank_cell(value)
    return _values_equal(value, blank_value)


def _is_blank_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _values_equal(left: Any, right: Any) -> bool:
    if _is_missing_scalar(left) and _is_missing_scalar(right):
        return True
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _is_missing_scalar(value: Any) -> bool:
    if isinstance(value, str):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _xref_column_keys_for_frame(
    frames: Mapping[str, Any],
    *,
    frame: str,
    config_id: str,
) -> list[Any] | None:
    meta = frames.get("_meta")
    if not isinstance(meta, Mapping):
        return None
    configs = meta.get(_XREF_META_KEY)
    if not isinstance(configs, Mapping):
        return None

    preferred = configs.get(config_id)
    if isinstance(preferred, Mapping) and preferred.get("matrix") == frame:
        column_keys = preferred.get("column_keys")
        return list(column_keys) if isinstance(column_keys, list) else None

    # Uniform family ambiguity policy: count every mapping entry claiming
    # the matrix identity before inspecting whether it carries a usable
    # column_keys payload. Partial entries participate in ambiguity; no
    # usable-payload precedence.
    matches: list[tuple[Any, Mapping[str, Any]]] = []
    for key, config in configs.items():
        if isinstance(config, Mapping) and config.get("matrix") == frame:
            matches.append((key, config))
    if len(matches) > 1:
        match_names = [key for key, _ in matches]
        raise ValueError(
            f"Ambiguous xref_crosstable metadata for matrix frame {frame!r}: "
            f"{match_names!r}. Provide sparse columns or name a matching transform."
        )
    if matches:
        column_keys = matches[0][1].get("column_keys")
        return list(column_keys) if isinstance(column_keys, list) else None
    return None


def _sparse_meta(frames: Mapping[str, Any], config_id: str) -> Mapping[str, Any] | None:
    meta = frames.get("_meta")
    if not isinstance(meta, Mapping):
        return None
    configs = meta.get(_META_KEY)
    if not isinstance(configs, Mapping):
        return None
    config = configs.get(config_id)
    return config if isinstance(config, Mapping) else None


def _write_sparse_meta(
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
