"""Cell value codec transformations.

This module owns the generic cell value <-> code/token conversion used by the
compact-transform path.  It validates syntax and configured value sets, but it
does not assign business meaning to codes.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

Frames = dict[str, Any]

_META_KEY = "cell_codecs"
_WHOLE_CELL_CODE = "whole_cell_code"
_SPLIT_TOKENS = "split_tokens"
_VALID_MODES = {_WHOLE_CELL_CODE, _SPLIT_TOKENS}
_VALID_CASE_NORMALIZERS = {"upper", "lower"}


@dataclass(frozen=True)
class ParsedCellValue:
    """Structured representation of one compact cell value."""

    mode: str
    values: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.values


def parse_cell_value(
    cell_value: Any,
    *,
    mode: str = _WHOLE_CELL_CODE,
    delimiter: str = "-",
    allowed_codes: Iterable[Any] | None = None,
    allowed_tokens: Iterable[Any] | None = None,
    allowed_from_legend: str | None = None,
    meta: Mapping[str, Any] | None = None,
    normalize_case: str | None = None,
    strip: bool = False,
) -> ParsedCellValue:
    """Parse and validate one compact cell string according to explicit config."""
    _ensure_valid_mode(mode)
    text = _cell_to_text(cell_value, strip=strip, normalize_case=normalize_case)
    if text == "":
        return ParsedCellValue(mode=mode, values=())

    if mode == _WHOLE_CELL_CODE:
        values = (text,)
        _validate_values(
            values,
            label="code",
            allowed_values=_allowed_values(
                meta=meta,
                explicit=allowed_codes,
                allowed_from_legend=allowed_from_legend,
                normalize_case=normalize_case,
                strip=strip,
            ),
        )
        return ParsedCellValue(mode=mode, values=values)

    _ensure_delimiter(delimiter)
    values = tuple(
        _normalize_text(part, strip=strip, normalize_case=normalize_case)
        for part in text.split(delimiter)
    )
    empty_tokens = [index for index, token in enumerate(values, start=1) if token == ""]
    if empty_tokens:
        raise ValueError(f"Cell value contains empty token(s) at positions: {empty_tokens!r}")
    _validate_values(
        values,
        label="token",
        allowed_values=_allowed_values(
            meta=meta,
            explicit=allowed_tokens,
            allowed_from_legend=allowed_from_legend,
            normalize_case=normalize_case,
            strip=strip,
        ),
    )
    return ParsedCellValue(mode=mode, values=values)


def serialize_cell_value(
    value: Any,
    *,
    mode: str = _WHOLE_CELL_CODE,
    delimiter: str = "-",
    allowed_codes: Iterable[Any] | None = None,
    allowed_tokens: Iterable[Any] | None = None,
    allowed_from_legend: str | None = None,
    meta: Mapping[str, Any] | None = None,
    canonical_order: Iterable[Any] | None = None,
    normalize_case: str | None = None,
    strip: bool = False,
) -> str:
    """Serialize already structured code/token values into a deterministic cell string."""
    _ensure_valid_mode(mode)
    values = _structured_values(value, mode=mode, strip=strip, normalize_case=normalize_case)
    if not values:
        return ""

    if mode == _WHOLE_CELL_CODE:
        if len(values) != 1:
            raise ValueError("whole_cell_code serialization requires exactly one code")
        _validate_values(
            values,
            label="code",
            allowed_values=_allowed_values(
                meta=meta,
                explicit=allowed_codes,
                allowed_from_legend=allowed_from_legend,
                normalize_case=normalize_case,
                strip=strip,
            ),
        )
        return values[0]

    _ensure_delimiter(delimiter)
    canonical_values = _canonicalize_values(
        values,
        canonical_order=canonical_order,
        strip=strip,
        normalize_case=normalize_case,
    )
    _validate_values(
        canonical_values,
        label="token",
        allowed_values=_allowed_values(
            meta=meta,
            explicit=allowed_tokens,
            allowed_from_legend=allowed_from_legend,
            normalize_case=normalize_case,
            strip=strip,
        ),
    )
    return delimiter.join(canonical_values)


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


def _cell_to_text(value: Any, *, strip: bool, normalize_case: str | None) -> str:
    if _is_empty_cell(value):
        return ""
    return _normalize_text(str(value), strip=strip, normalize_case=normalize_case)


def _normalize_text(value: str, *, strip: bool, normalize_case: str | None) -> str:
    _ensure_valid_normalizer(normalize_case)
    text = value.strip() if strip else value
    if normalize_case == "upper":
        return text.upper()
    if normalize_case == "lower":
        return text.lower()
    return text


def _structured_values(
    value: Any,
    *,
    mode: str,
    strip: bool,
    normalize_case: str | None,
) -> tuple[str, ...]:
    if isinstance(value, ParsedCellValue):
        if value.mode != mode:
            raise ValueError(f"Parsed cell mode {value.mode!r} does not match requested mode {mode!r}")
        raw_values = value.values
    elif isinstance(value, str):
        raw_values = (value,)
    elif isinstance(value, Sequence):
        raw_values = tuple(value)
    else:
        raw_values = (value,)

    normalized = tuple(
        _cell_to_text(raw, strip=strip, normalize_case=normalize_case)
        for raw in raw_values
    )
    if any(item == "" for item in normalized):
        return tuple(item for item in normalized if item != "")
    return normalized


def _canonicalize_values(
    values: tuple[str, ...],
    *,
    canonical_order: Iterable[Any] | None,
    strip: bool,
    normalize_case: str | None,
) -> tuple[str, ...]:
    if canonical_order is None:
        return values

    ordered = tuple(
        _cell_to_text(item, strip=strip, normalize_case=normalize_case)
        for item in canonical_order
    )
    duplicates = _duplicates(ordered)
    if duplicates:
        raise ValueError(f"canonical_order contains duplicate values: {duplicates!r}")

    order_index = {item: index for index, item in enumerate(ordered)}
    return tuple(
        value
        for _, value in sorted(
            enumerate(values),
            key=lambda indexed_value: (
                order_index.get(indexed_value[1], len(order_index)),
                indexed_value[0],
            ),
        )
    )


def _allowed_values(
    *,
    meta: Mapping[str, Any] | None,
    explicit: Iterable[Any] | None,
    allowed_from_legend: str | None,
    strip: bool,
    normalize_case: str | None,
) -> tuple[str, ...] | None:
    values: list[str] = []
    if explicit is not None:
        values.extend(
            _cell_to_text(item, strip=strip, normalize_case=normalize_case)
            for item in explicit
        )
    if allowed_from_legend:
        values.extend(
            _cell_to_text(item, strip=strip, normalize_case=normalize_case)
            for item in _legend_tokens(meta, allowed_from_legend)
        )
    if explicit is None and not allowed_from_legend:
        return None

    duplicates = _duplicates(values)
    if duplicates:
        raise ValueError(f"Allowed value set contains duplicate values: {duplicates!r}")
    return tuple(values)


def _legend_tokens(meta: Mapping[str, Any] | None, legend_name: str) -> tuple[Any, ...]:
    if not isinstance(meta, Mapping):
        raise KeyError(
            f"allowed_from_legend references legend block {legend_name!r}, "
            "but _meta.legend_blocks is missing"
        )
    raw = meta.get("legend_blocks")
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
        raise KeyError(
            f"allowed_from_legend references legend block {legend_name!r}, "
            "but no matching legend block was found in _meta.legend_blocks"
        )
    entries = spec.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Legend block {legend_name!r} requires a non-empty entries list")

    tokens: list[Any] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, Mapping):
            raise ValueError(f"Legend block {legend_name!r} entry {index} must be a mapping")
        token = entry.get("token")
        if _is_empty_cell(token):
            raise ValueError(f"Legend block {legend_name!r} entry {index} has an empty token")
        tokens.append(token)
    return tuple(tokens)


def _validate_values(
    values: tuple[str, ...],
    *,
    label: str,
    allowed_values: tuple[str, ...] | None,
) -> None:
    if allowed_values is None:
        return
    invalid = [value for value in values if value not in allowed_values]
    if invalid:
        raise ValueError(f"Invalid cell {label}(s): {invalid!r}")


def _ensure_valid_mode(mode: str) -> None:
    if mode not in _VALID_MODES:
        raise ValueError(
            f"Unsupported cell codec mode {mode!r}; expected one of "
            f"{sorted(_VALID_MODES)!r}. Use 'whole_cell_code' when punctuation "
            "such as '-' is part of one code; use 'split_tokens' only with an "
            "explicit delimiter."
        )


def _ensure_valid_normalizer(normalize_case: str | None) -> None:
    if normalize_case is not None and normalize_case not in _VALID_CASE_NORMALIZERS:
        raise ValueError(
            "normalize_case must be one of "
            f"{sorted(_VALID_CASE_NORMALIZERS)!r} or None"
        )


def _ensure_delimiter(delimiter: str) -> None:
    if not isinstance(delimiter, str) or delimiter == "":
        raise ValueError(
            "split_tokens mode requires a non-empty delimiter; punctuation is "
            "not interpreted as token structure unless mode='split_tokens' and "
            "delimiter is configured."
        )


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


def _values_equal(left: Any, right: Any) -> bool:
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _is_empty_cell(cell_value: Any) -> bool:
    if cell_value is None:
        return True
    if isinstance(cell_value, str):
        return cell_value == ""
    try:
        return bool(pd.isna(cell_value))
    except (TypeError, ValueError):
        return False


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


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
