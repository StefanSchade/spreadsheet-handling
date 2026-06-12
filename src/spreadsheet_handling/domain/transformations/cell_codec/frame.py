"""Cell value codec - DataFrame projection (frame side).

Frame half of the ``cell_codec`` package. Owns the DataFrame-level decode /
encode publics, the frame-shape guards, the grouping helper, and the
``_meta.cell_codecs`` write shape. Delegates per-cell parse / serialize to
``.scalar`` via its public entry points; carries no scalar-helper imports.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain._cell_primitives import _is_empty_cell, _values_equal

from .scalar import _WHOLE_CELL_CODE, parse_cell_value, serialize_cell_value

Frames = dict[str, Any]

_META_KEY = "cell_codecs"


def decode_cell_values(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    value: str = "value",
    code: str = "code",
    passthrough_columns: Iterable[Any] | None = None,
    drop_empty: bool = True,
    mode: str = _WHOLE_CELL_CODE,
    delimiter: str = "-",
    allowed_codes: Iterable[Any] | None = None,
    allowed_tokens: Iterable[Any] | None = None,
    allowed_from_legend: str | None = None,
    normalize_case: str | None = None,
    strip: bool = False,
    name: str | None = None,
) -> Frames:
    """Decode one DataFrame cell-value column into explicit code/token rows.

    ``drop_empty=True`` is sparse and can drop empty-only groups.  Use
    ``drop_empty=False`` when empty groups must survive a lossless roundtrip.
    """
    source_frame = _require_frame(frames, source)
    _ensure_columns(source_frame, [value], frame_name=source)
    passthrough = (
        _as_list(passthrough_columns, "passthrough_columns")
        if passthrough_columns is not None
        else [column for column in source_frame.columns if column != value]
    )
    _ensure_columns(source_frame, passthrough, frame_name=source)
    _ensure_output_name_does_not_collide(passthrough, code=code)

    meta = _meta_from_frames(frames)
    records: list[dict[Any, Any]] = []
    for _, source_row in source_frame.iterrows():
        parsed = parse_cell_value(
            source_row[value],
            mode=mode,
            delimiter=delimiter,
            allowed_codes=allowed_codes,
            allowed_tokens=allowed_tokens,
            allowed_from_legend=allowed_from_legend,
            meta=meta,
            normalize_case=normalize_case,
            strip=strip,
        )
        base = {column: source_row[column] for column in passthrough}
        if parsed.is_empty:
            if not drop_empty:
                records.append({**base, code: ""})
            continue
        for item in parsed.values:
            records.append({**base, code: item})

    decoded = pd.DataFrame(records, columns=[*passthrough, code])
    out: dict[str, Any] = dict(frames)
    out[output] = decoded
    _write_codec_meta(
        out,
        config_id=name or output,
        payload={
            "operation": "decode_cell_values",
            "source": source,
            "output": output,
            "value": value,
            "code": code,
            "passthrough_columns": list(passthrough),
            "drop_empty": bool(drop_empty),
            **_codec_config_payload(
                mode=mode,
                delimiter=delimiter,
                allowed_codes=allowed_codes,
                allowed_tokens=allowed_tokens,
                allowed_from_legend=allowed_from_legend,
                canonical_order=None,
                normalize_case=normalize_case,
                strip=strip,
            ),
        },
    )
    return out


def encode_cell_values(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    group_by: str | Iterable[Any],
    code: str = "code",
    value: str = "value",
    mode: str = _WHOLE_CELL_CODE,
    delimiter: str = "-",
    allowed_codes: Iterable[Any] | None = None,
    allowed_tokens: Iterable[Any] | None = None,
    allowed_from_legend: str | None = None,
    canonical_order: Iterable[Any] | None = None,
    normalize_case: str | None = None,
    strip: bool = False,
    name: str | None = None,
) -> Frames:
    """Encode explicit code/token rows back into compact cell values.

    The ``cell_codecs`` metadata written by this function documents the
    resolved contract; it is not an implicit runtime config resolver.
    """
    source_frame = _require_frame(frames, source)
    group_cols = _as_list(group_by, "group_by")
    _ensure_columns(source_frame, [*group_cols, code], frame_name=source)
    _ensure_output_name_does_not_collide(group_cols, code=value)

    meta = _meta_from_frames(frames)
    rows_by_group = _ordered_groups(source_frame, group_cols, code)
    records: list[dict[Any, Any]] = []
    for identity, items in rows_by_group:
        cell_items = [
            item for item in items
            if not _is_empty_cell(item)
        ]
        cell_text = serialize_cell_value(
            cell_items,
            mode=mode,
            delimiter=delimiter,
            allowed_codes=allowed_codes,
            allowed_tokens=allowed_tokens,
            allowed_from_legend=allowed_from_legend,
            meta=meta,
            canonical_order=canonical_order,
            normalize_case=normalize_case,
            strip=strip,
        )
        record = {
            column: identity[index]
            for index, column in enumerate(group_cols)
        }
        records.append({**record, value: cell_text})

    encoded = pd.DataFrame(records, columns=[*group_cols, value])
    out: dict[str, Any] = dict(frames)
    out[output] = encoded
    _write_codec_meta(
        out,
        config_id=name or output,
        payload={
            "operation": "encode_cell_values",
            "source": source,
            "output": output,
            "group_by": list(group_cols),
            "code": code,
            "value": value,
            **_codec_config_payload(
                mode=mode,
                delimiter=delimiter,
                allowed_codes=allowed_codes,
                allowed_tokens=allowed_tokens,
                allowed_from_legend=allowed_from_legend,
                canonical_order=canonical_order,
                normalize_case=normalize_case,
                strip=strip,
            ),
        },
    )
    return out


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Frame {name!r} not found")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Frame {name!r} must be a pandas DataFrame")
    if isinstance(frame.columns, pd.MultiIndex) or any(isinstance(col, tuple) for col in frame.columns):
        raise ValueError(
            f"Frame {name!r} has MultiIndex/tuple columns; "
            "FTR-CELL-CODEC first slice requires flat column labels"
        )
    return frame


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
            "FTR-CELL-CODEC first slice requires flat labels"
        )
    return result


def _ensure_columns(df: pd.DataFrame, columns: Iterable[Any], *, frame_name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"Frame {frame_name!r} is missing columns: {missing!r}")


def _ensure_output_name_does_not_collide(columns: Iterable[Any], *, code: str) -> None:
    if code in columns:
        raise ValueError(f"Output column {code!r} collides with existing passthrough/group column")


def _ordered_groups(
    source: pd.DataFrame,
    group_cols: list[Any],
    code: str,
) -> list[tuple[tuple[Any, ...], list[Any]]]:
    groups: list[tuple[tuple[Any, ...], list[Any]]] = []
    for _, row in source.iterrows():
        identity = tuple(row[column] for column in group_cols)
        for existing_identity, items in groups:
            if _identity_equal(existing_identity, identity):
                items.append(row[code])
                break
        else:
            groups.append((identity, [row[code]]))
    return groups


def _identity_equal(left: tuple[Any, ...], right: tuple[Any, ...]) -> bool:
    return len(left) == len(right) and all(_values_equal(a, b) for a, b in zip(left, right))


def _meta_from_frames(frames: Mapping[str, Any]) -> Mapping[str, Any]:
    meta = frames.get("_meta") if isinstance(frames, Mapping) else None
    return meta if isinstance(meta, Mapping) else {}


def _codec_config_payload(
    *,
    mode: str,
    delimiter: str,
    allowed_codes: Iterable[Any] | None,
    allowed_tokens: Iterable[Any] | None,
    allowed_from_legend: str | None,
    canonical_order: Iterable[Any] | None,
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
    if canonical_order is not None:
        payload["canonical_order"] = list(canonical_order)
    if normalize_case is not None:
        payload["normalize_case"] = normalize_case
    return payload


def _write_codec_meta(
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
