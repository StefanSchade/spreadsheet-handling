"""Cell value codec - per-cell parse/serialize (scalar side).

Scalar half of the ``cell_codec`` package. Owns the per-cell parse /
serialize contract, the mode / normaliser / delimiter guards, the
allowed-value resolver (including the ``_meta.legend_blocks`` read shape),
and the text-normalisation helpers. Bodies are verbatim moves out of the
original flat module.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from spreadsheet_handling.domain._cell_primitives import _is_empty_cell
from spreadsheet_handling.domain.transformations._legend_blocks import _read_legend_block

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
    return tuple(token for token, _group in _read_legend_block(meta, legend_name))


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


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates
