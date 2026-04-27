"""Compact multi-axis transformations.

This module composes the generic XRef and cell-codec primitives. It keeps
matrix axes, cell codes, and optional code groups generic; domain meaning stays
outside this layer.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from .cell_codec import decode_cell_values, encode_cell_values
from .xref_crosstable import contract_xref, expand_xref

Frames = dict[str, Any]

_META_KEY = "compact_multiaxis"


def expand_compact_multiaxis(
    frames: Mapping[str, Any],
    *,
    matrix: str,
    output: str,
    row_keys: str | Iterable[Any],
    value_columns: Iterable[Any] | None = None,
    column_key: str = "column_key",
    value: str = "value",
    code: str = "code",
    group: str | None = None,
    mode: str = "whole_cell_code",
    delimiter: str = "-",
    allowed_codes: Iterable[Any] | None = None,
    allowed_tokens: Iterable[Any] | None = None,
    allowed_from_legend: str | None = None,
    code_groups: Mapping[Any, Any] | None = None,
    normalize_case: str | None = None,
    strip: bool = False,
    drop_empty: bool = True,
    dense_axes: Mapping[str, Any] | None = None,
    name: str | None = None,
) -> Frames:
    """Expand a compact matrix into generic explicit code rows."""
    _reject_dense_axes(dense_axes)
    config_id = name or output
    row_key_cols = _as_list(row_keys, "row_keys")
    passthrough = [*row_key_cols, column_key]
    _ensure_distinct_output_columns(passthrough, code=code, group=group)

    temp_relation = _temp_frame_name(frames, f"__compact_multiaxis_{config_id}_xref")
    expanded = expand_xref(
        frames,
        matrix=matrix,
        output=temp_relation,
        row_keys=row_key_cols,
        value_columns=value_columns,
        column_key=column_key,
        value=value,
        drop_empty=False,
        name=config_id,
    )
    decoded = decode_cell_values(
        expanded,
        source=temp_relation,
        output=output,
        value=value,
        code=code,
        passthrough_columns=passthrough,
        drop_empty=drop_empty,
        mode=mode,
        delimiter=delimiter,
        allowed_codes=allowed_codes,
        allowed_tokens=allowed_tokens,
        allowed_from_legend=allowed_from_legend,
        normalize_case=normalize_case,
        strip=strip,
        name=config_id,
    )

    out: dict[str, Any] = dict(decoded)
    out.pop(temp_relation, None)
    if group is not None:
        out[output] = _with_group_column(
            out[output],
            code=code,
            group=group,
            meta=_meta_from_frames(frames),
            allowed_from_legend=allowed_from_legend,
            code_groups=code_groups,
            normalize_case=normalize_case,
            strip=strip,
        )

    _write_multiaxis_meta(
        out,
        config_id=config_id,
        payload={
            "operation": "expand_compact_multiaxis",
            "matrix": matrix,
            "output": output,
            "row_keys": list(row_key_cols),
            "value_columns": None if value_columns is None else list(value_columns),
            "column_key": column_key,
            "value": value,
            "code": code,
            "group": group,
            "drop_empty": bool(drop_empty),
            **_codec_payload(
                mode=mode,
                delimiter=delimiter,
                allowed_codes=allowed_codes,
                allowed_tokens=allowed_tokens,
                allowed_from_legend=allowed_from_legend,
                code_groups=code_groups,
                normalize_case=normalize_case,
                strip=strip,
            ),
        },
    )
    return out


def contract_compact_multiaxis(
    frames: Mapping[str, Any],
    *,
    relation: str,
    output: str,
    row_keys: str | Iterable[Any],
    column_key: str = "column_key",
    code: str = "code",
    value: str = "value",
    column_keys: Iterable[Any] | None = None,
    fill_value: Any = "",
    mode: str = "whole_cell_code",
    delimiter: str = "-",
    allowed_codes: Iterable[Any] | None = None,
    allowed_tokens: Iterable[Any] | None = None,
    allowed_from_legend: str | None = None,
    canonical_order: Iterable[Any] | None = None,
    normalize_case: str | None = None,
    strip: bool = False,
    dense_axes: Mapping[str, Any] | None = None,
    name: str | None = None,
) -> Frames:
    """Contract generic explicit code rows back into a compact matrix."""
    _reject_dense_axes(dense_axes)
    config_id = name or relation
    row_key_cols = _as_list(row_keys, "row_keys")
    group_by = [*row_key_cols, column_key]

    temp_relation = _temp_frame_name(frames, f"__compact_multiaxis_{config_id}_encoded")
    encoded = encode_cell_values(
        frames,
        source=relation,
        output=temp_relation,
        group_by=group_by,
        code=code,
        value=value,
        mode=mode,
        delimiter=delimiter,
        allowed_codes=allowed_codes,
        allowed_tokens=allowed_tokens,
        allowed_from_legend=allowed_from_legend,
        canonical_order=canonical_order,
        normalize_case=normalize_case,
        strip=strip,
        name=config_id,
    )
    contracted = contract_xref(
        encoded,
        relation=temp_relation,
        output=output,
        row_keys=row_key_cols,
        column_key=column_key,
        value=value,
        column_keys=column_keys,
        fill_value=fill_value,
        name=config_id,
    )

    out: dict[str, Any] = dict(contracted)
    out.pop(temp_relation, None)
    _write_multiaxis_meta(
        out,
        config_id=config_id,
        payload={
            "operation": "contract_compact_multiaxis",
            "relation": relation,
            "matrix": output,
            "row_keys": list(row_key_cols),
            "column_key": column_key,
            "code": code,
            "value": value,
            "column_keys": None if column_keys is None else list(column_keys),
            "fill_value": fill_value,
            "canonical_order": None if canonical_order is None else list(canonical_order),
            **_codec_payload(
                mode=mode,
                delimiter=delimiter,
                allowed_codes=allowed_codes,
                allowed_tokens=allowed_tokens,
                allowed_from_legend=allowed_from_legend,
                code_groups=None,
                normalize_case=normalize_case,
                strip=strip,
            ),
        },
    )
    return out


def _with_group_column(
    frame: pd.DataFrame,
    *,
    code: str,
    group: str,
    meta: Mapping[str, Any],
    allowed_from_legend: str | None,
    code_groups: Mapping[Any, Any] | None,
    normalize_case: str | None,
    strip: bool,
) -> pd.DataFrame:
    if code not in frame.columns:
        raise KeyError(f"Frame is missing code column {code!r}")
    if group in frame.columns:
        raise ValueError(f"group column {group!r} collides with an existing output column")

    lookup = _group_lookup(
        meta=meta,
        allowed_from_legend=allowed_from_legend,
        code_groups=code_groups,
        normalize_case=normalize_case,
        strip=strip,
    )
    out = frame.copy()
    out[group] = [
        lookup.get(_normalize_key(value, normalize_case=normalize_case, strip=strip), "")
        for value in out[code].tolist()
    ]
    return out


def _group_lookup(
    *,
    meta: Mapping[str, Any],
    allowed_from_legend: str | None,
    code_groups: Mapping[Any, Any] | None,
    normalize_case: str | None,
    strip: bool,
) -> dict[str, Any]:
    lookup: dict[str, Any] = {}
    if allowed_from_legend:
        for token, group_value in _legend_groups(meta, allowed_from_legend).items():
            key = _normalize_key(token, normalize_case=normalize_case, strip=strip)
            if key in lookup and lookup[key] != group_value:
                raise ValueError(f"Conflicting group value for code {key!r}")
            lookup[key] = group_value

    if code_groups:
        for token, group_value in code_groups.items():
            key = _normalize_key(token, normalize_case=normalize_case, strip=strip)
            if key in lookup and lookup[key] != group_value:
                raise ValueError(f"Conflicting group value for code {key!r}")
            lookup[key] = group_value
    return lookup


def _legend_groups(meta: Mapping[str, Any], legend_name: str) -> dict[Any, Any]:
    raw = meta.get("legend_blocks")
    spec: Any
    if isinstance(raw, Mapping):
        spec = raw.get(legend_name)
    elif isinstance(raw, list):
        spec = next(
            (
                item for index, item in enumerate(raw, start=1)
                if isinstance(item, Mapping)
                and str(item.get("name") or item.get("id") or f"legend_{index}") == legend_name
            ),
            None,
        )
    else:
        spec = None

    if not isinstance(spec, Mapping):
        raise KeyError(f"Legend block {legend_name!r} not found")
    entries = spec.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Legend block {legend_name!r} requires a non-empty entries list")

    groups: dict[Any, Any] = {}
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, Mapping):
            raise ValueError(f"Legend block {legend_name!r} entry {index} must be a mapping")
        token = entry.get("token")
        if token is None or str(token) == "":
            raise ValueError(f"Legend block {legend_name!r} entry {index} has an empty token")
        group_value = entry.get("group", "")
        if token in groups and groups[token] != group_value:
            raise ValueError(f"Legend block {legend_name!r} has conflicting group values for {token!r}")
        groups[token] = group_value
    return groups


def _as_list(value: str | Iterable[Any] | None, field_name: str) -> list[Any]:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, str):
        result = [value]
    else:
        result = list(value)
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    if any(isinstance(item, tuple) for item in result):
        raise ValueError(
            f"{field_name} contains tuple labels; "
            "FTR-COMPACT-MULTIAXIS first slice requires flat labels"
        )
    return result


def _ensure_distinct_output_columns(
    passthrough: Iterable[Any],
    *,
    code: str,
    group: str | None,
) -> None:
    reserved = {code}
    if group is not None:
        reserved.add(group)
    collisions = [column for column in passthrough if column in reserved]
    if collisions:
        raise ValueError(f"Output columns collide with passthrough columns: {collisions!r}")
    if group is not None and group == code:
        raise ValueError("group and code output names must differ")


def _reject_dense_axes(dense_axes: Mapping[str, Any] | None) -> None:
    if dense_axes is not None:
        raise NotImplementedError(
            "dense_axes is a future explicit reconstruction contract and is not implemented "
            "by FTR-COMPACT-MULTIAXIS first slice"
        )


def _normalize_key(value: Any, *, normalize_case: str | None, strip: bool) -> str:
    text = str(value)
    if strip:
        text = text.strip()
    if normalize_case == "upper":
        return text.upper()
    if normalize_case == "lower":
        return text.lower()
    return text


def _temp_frame_name(frames: Mapping[str, Any], base: str) -> str:
    candidate = base
    index = 2
    while candidate in frames:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _meta_from_frames(frames: Mapping[str, Any]) -> Mapping[str, Any]:
    meta = frames.get("_meta") if isinstance(frames, Mapping) else None
    return meta if isinstance(meta, Mapping) else {}


def _codec_payload(
    *,
    mode: str,
    delimiter: str,
    allowed_codes: Iterable[Any] | None,
    allowed_tokens: Iterable[Any] | None,
    allowed_from_legend: str | None,
    code_groups: Mapping[Any, Any] | None,
    normalize_case: str | None,
    strip: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": mode,
        "delimiter": delimiter,
        "strip": bool(strip),
    }
    if allowed_codes is not None:
        payload["allowed_codes"] = list(allowed_codes)
    if allowed_tokens is not None:
        payload["allowed_tokens"] = list(allowed_tokens)
    if allowed_from_legend is not None:
        payload["allowed_from_legend"] = allowed_from_legend
    if code_groups is not None:
        payload["code_groups"] = {
            _normalize_key(key, normalize_case=normalize_case, strip=strip): value
            for key, value in code_groups.items()
        }
    if normalize_case is not None:
        payload["normalize_case"] = normalize_case
    return payload


def _write_multiaxis_meta(
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
