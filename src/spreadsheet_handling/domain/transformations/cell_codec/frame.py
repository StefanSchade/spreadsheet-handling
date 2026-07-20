"""Cell value codec - DataFrame projection (frame side).

Frame half of the ``cell_codec`` package. Owns the DataFrame-level decode /
encode publics, the frame-shape guards, and the grouping helper. Delegates
per-cell parse / serialize to ``.scalar`` via its public entry points;
carries no scalar-helper imports.

Cell Codec intent lives entirely in explicit step configuration
(``codec_intent`` for the position-based contract, explicit ``mode`` plus
codec parameters for the historical code-row contract consumed by
``compact_multiaxis``). No ``_meta.cell_codecs`` entries are produced: no
runtime consumer ever read them, so the family follows the projection-family
rule that metadata without a concrete decision consumer is not persisted.
Legacy ``_meta.cell_codecs`` payloads in old sidecars or workbooks are
tolerated pass-through sediment.

The codec is string-oriented (see
``ADR-VISIBLE-CELL-TYPING-STRING-SUBSTRATE``): position-based participating
values must be strings (or empty); decoded values are strings, and empty /
missing participating values normalize to the configured ``absent_value``
token and decode back to ``""``.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain._cell_primitives import _is_empty_cell, _values_equal
from spreadsheet_handling.domain.tabular import (
    ensure_unique_field_declaration,
    ensure_unique_physical_column_labels,
    is_scalar_addressable_label,
)

from .scalar import parse_cell_value, serialize_cell_value

# Cell Codec shares the physical-frame column-label boundary with the other
# tabular-domain families (see ``domain/tabular``): physical labels must be
# non-missing, hashable, uniquely and deterministically comparable, and
# scalar-addressable. This is distinct from the string-oriented contract on
# participating *cell values*.
_ensure_unique_physical_labels = ensure_unique_physical_column_labels

Frames = dict[str, Any]


class _Unset:
    """Sentinel marking 'argument not explicitly supplied'.

    Distinct from a real default so the public entry points can tell a caller
    that explicitly passed a historical parameter from one that did not touch
    it, without redesigning pipeline argument binding.
    """

    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "<unset>"


_UNSET: Any = _Unset()


def _supplied(value: Any, default: Any) -> Any:
    """Resolve a sentinel-defaulted argument to its real default."""
    return default if value is _UNSET else value


def _reject_historical_args_with_intent(supplied: Mapping[str, Any]) -> None:
    """Enforce position/historical mutual exclusion at the public entry points.

    ``codec_intent`` selects the position-based contract; supplying any
    historical code-row parameter alongside it is a configuration conflict,
    not silent position precedence. Only explicitly supplied arguments (not
    untouched function defaults) count.
    """
    conflicting = sorted(
        name for name, value in supplied.items() if value is not _UNSET
    )
    if conflicting:
        raise ValueError(
            "codec_intent (position-based) is mutually exclusive with the "
            "historical code-row parameters, but was supplied together with: "
            f"{conflicting!r}. Use either codec_intent or the historical "
            "mode-based parameters, not both."
        )


def decode_cell_values(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    codec_intent: Mapping[str, Any] | None = None,
    value: Any = _UNSET,
    code: Any = _UNSET,
    passthrough_columns: Any = _UNSET,
    drop_empty: Any = _UNSET,
    mode: Any = _UNSET,
    delimiter: Any = _UNSET,
    allowed_codes: Any = _UNSET,
    allowed_tokens: Any = _UNSET,
    allowed_from_legend: Any = _UNSET,
    normalize_case: Any = _UNSET,
    strip: Any = _UNSET,
    name: str | None = None,
) -> Frames:
    """Decode a compact column using explicit codec intent.

    The position-based ``codec_intent`` and the historical code-row mode-based
    parameters are mutually exclusive: supplying both fails deterministically
    rather than silently applying position precedence. Historical code/token
    mode remains available only when ``mode`` is passed explicitly by current
    composition callers.
    """
    if codec_intent is not None:
        _reject_historical_args_with_intent(
            {
                "value": value,
                "code": code,
                "passthrough_columns": passthrough_columns,
                "drop_empty": drop_empty,
                "mode": mode,
                "delimiter": delimiter,
                "allowed_codes": allowed_codes,
                "allowed_tokens": allowed_tokens,
                "allowed_from_legend": allowed_from_legend,
                "normalize_case": normalize_case,
                "strip": strip,
            }
        )
        return _decode_position_based(
            frames,
            source=source,
            output=output,
            codec_intent=codec_intent,
            name=name,
        )
    if mode is _UNSET or mode is None:
        raise ValueError("codec intent is required for decoding compact cell values")
    return _decode_legacy_code_rows(
        frames,
        source=source,
        output=output,
        value=_supplied(value, "value"),
        code=_supplied(code, "code"),
        passthrough_columns=_supplied(passthrough_columns, None),
        drop_empty=_supplied(drop_empty, True),
        mode=mode,
        delimiter=_supplied(delimiter, "-"),
        allowed_codes=_supplied(allowed_codes, None),
        allowed_tokens=_supplied(allowed_tokens, None),
        allowed_from_legend=_supplied(allowed_from_legend, None),
        normalize_case=_supplied(normalize_case, None),
        strip=_supplied(strip, False),
        name=name,
    )


def _decode_legacy_code_rows(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    value: str,
    code: str,
    passthrough_columns: Iterable[Any] | None,
    drop_empty: bool,
    mode: str,
    delimiter: str,
    allowed_codes: Iterable[Any] | None,
    allowed_tokens: Iterable[Any] | None,
    allowed_from_legend: str | None,
    normalize_case: str | None,
    strip: bool,
    name: str | None,
) -> Frames:
    del name
    source_frame = _require_frame(frames, source)
    _ensure_unique_physical_labels(source_frame, frame_name=source)
    _ensure_addressable_selector(value, field_name="value")
    _ensure_columns(source_frame, [value], frame_name=source)
    passthrough = (
        _as_list(passthrough_columns, "passthrough_columns")
        if passthrough_columns is not None
        else [column for column in source_frame.columns if column != value]
    )
    # Reject duplicate/unaddressable passthrough declarations before output so
    # duplicate declarations never create duplicate output columns.
    _ensure_configured_field_labels(passthrough, field_name="passthrough_columns")
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
    return out


def encode_cell_values(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    codec_intent: Mapping[str, Any] | None = None,
    group_by: Any = _UNSET,
    code: Any = _UNSET,
    value: Any = _UNSET,
    mode: Any = _UNSET,
    delimiter: Any = _UNSET,
    allowed_codes: Any = _UNSET,
    allowed_tokens: Any = _UNSET,
    allowed_from_legend: Any = _UNSET,
    canonical_order: Any = _UNSET,
    normalize_case: Any = _UNSET,
    strip: Any = _UNSET,
    name: str | None = None,
) -> Frames:
    """Encode configured slot columns into a compact column.

    The position-based ``codec_intent`` and the historical code-row mode-based
    parameters are mutually exclusive: supplying both fails deterministically
    rather than silently applying position precedence. Historical code/token
    mode remains available only when ``mode`` is passed explicitly by current
    composition callers, and requires ``group_by``.
    """
    if codec_intent is not None:
        _reject_historical_args_with_intent(
            {
                "group_by": group_by,
                "code": code,
                "value": value,
                "mode": mode,
                "delimiter": delimiter,
                "allowed_codes": allowed_codes,
                "allowed_tokens": allowed_tokens,
                "allowed_from_legend": allowed_from_legend,
                "canonical_order": canonical_order,
                "normalize_case": normalize_case,
                "strip": strip,
            }
        )
        return _encode_position_based(
            frames,
            source=source,
            output=output,
            codec_intent=codec_intent,
            name=name,
        )
    if mode is _UNSET or mode is None:
        raise ValueError("codec intent is required for encoding compact cell values")
    if group_by is _UNSET or group_by is None:
        raise ValueError("group_by is required for legacy code-row encoding")
    return _encode_legacy_code_rows(
        frames,
        source=source,
        output=output,
        group_by=group_by,
        code=_supplied(code, "code"),
        value=_supplied(value, "value"),
        mode=mode,
        delimiter=_supplied(delimiter, "-"),
        allowed_codes=_supplied(allowed_codes, None),
        allowed_tokens=_supplied(allowed_tokens, None),
        allowed_from_legend=_supplied(allowed_from_legend, None),
        canonical_order=_supplied(canonical_order, None),
        normalize_case=_supplied(normalize_case, None),
        strip=_supplied(strip, False),
        name=name,
    )


def _encode_legacy_code_rows(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    group_by: str | Iterable[Any],
    code: str,
    value: str,
    mode: str,
    delimiter: str,
    allowed_codes: Iterable[Any] | None,
    allowed_tokens: Iterable[Any] | None,
    allowed_from_legend: str | None,
    canonical_order: Iterable[Any] | None,
    normalize_case: str | None,
    strip: bool,
    name: str | None,
) -> Frames:
    del name
    source_frame = _require_frame(frames, source)
    _ensure_unique_physical_labels(source_frame, frame_name=source)
    group_cols = _as_list(group_by, "group_by")
    _ensure_configured_field_labels(group_cols, field_name="group_by")
    _ensure_addressable_selector(code, field_name="code")
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


def _ensure_configured_field_labels(columns: Iterable[Any], *, field_name: str) -> None:
    """Duplicate + scalar-addressability guard for a configured selector list.

    Configured selectors (``participating_columns``, ``group_by``,
    ``passthrough_columns``) must be unique and must be able to address a
    scalar column before any pandas membership/selection runs, so an
    unhashable/missing/ambiguous selector receives a deterministic codec
    diagnostic instead of a raw pandas ``TypeError`` from
    ``_ensure_columns`` membership. Duplicate declarations must never create
    duplicate output columns.
    """
    materialized = list(columns)
    ensure_unique_field_declaration(materialized, field_name=field_name)
    unaddressable = [
        column for column in materialized if not is_scalar_addressable_label(column)
    ]
    if unaddressable:
        raise ValueError(
            f"{field_name} contains label(s) that cannot address a scalar "
            f"column: {unaddressable!r}; configured labels must be non-missing, "
            "hashable, and deterministically comparable"
        )


def _ensure_addressable_selector(label: Any, *, field_name: str) -> None:
    """Scalar-addressability guard for a single configured column selector.

    Ensures a configured scalar selector (``code`` / ``value``) can address a
    column before it reaches pandas membership/selection.
    """
    if not is_scalar_addressable_label(label):
        raise ValueError(
            f"{field_name} label {label!r} cannot address a scalar column; "
            "configured labels must be non-missing, hashable, and "
            "deterministically comparable"
        )


def _encode_position_based(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    codec_intent: Mapping[str, Any],
    name: str | None,
) -> Frames:
    del name
    source_frame = _require_frame(frames, source)
    _ensure_unique_physical_labels(source_frame, frame_name=source)
    intent = _position_intent(codec_intent)
    _ensure_columns(source_frame, intent["participating_columns"], frame_name=source)
    _reject_helper_participating_columns(frames, source, intent["participating_columns"])

    compact_column = intent["compact_column"]
    passthrough = [
        column for column in source_frame.columns
        if column not in intent["participating_columns"]
    ]
    _ensure_output_name_does_not_collide(passthrough, code=compact_column)

    records: list[dict[Any, Any]] = []
    for _, source_row in source_frame.iterrows():
        compact_value = _encode_compact_value(
            source_row,
            participating_columns=intent["participating_columns"],
            separator=intent["separator"],
            absent_value=intent["absent_value"],
        )
        record = {column: source_row[column] for column in passthrough}
        records.append({**record, compact_column: compact_value})

    out: dict[str, Any] = dict(frames)
    out[output] = pd.DataFrame(records, columns=[*passthrough, compact_column])
    return out


def _decode_position_based(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    codec_intent: Mapping[str, Any],
    name: str | None,
) -> Frames:
    del name
    source_frame = _require_frame(frames, source)
    _ensure_unique_physical_labels(source_frame, frame_name=source)
    intent = _position_intent(codec_intent)
    compact_column = intent["compact_column"]
    _ensure_columns(source_frame, [compact_column], frame_name=source)
    passthrough = [column for column in source_frame.columns if column != compact_column]
    decoded_overlap = [
        column for column in intent["participating_columns"] if column in passthrough
    ]
    if decoded_overlap:
        raise ValueError(
            f"decoded participating column(s) {decoded_overlap!r} already "
            f"exist on frame {source!r}; decoding would silently overwrite "
            "them"
        )

    records: list[dict[Any, Any]] = []
    for _, source_row in source_frame.iterrows():
        expanded_values = _decode_compact_value(
            source_row[compact_column],
            participating_columns=intent["participating_columns"],
            separator=intent["separator"],
            absent_value=intent["absent_value"],
        )
        record = {column: source_row[column] for column in passthrough}
        records.append({**record, **expanded_values})

    out: dict[str, Any] = dict(frames)
    out[output] = pd.DataFrame(records, columns=[*passthrough, *intent["participating_columns"]])
    return out


def _position_intent(codec_intent: Mapping[str, Any]) -> dict[str, Any]:
    participating_columns = _as_list(
        codec_intent.get("participating_columns"),
        "codec_intent.participating_columns",
    )
    _ensure_configured_field_labels(
        participating_columns, field_name="codec_intent.participating_columns"
    )
    compact_column = codec_intent.get("compact_column")
    if not isinstance(compact_column, str) or compact_column == "":
        raise ValueError("codec_intent.compact_column must be a non-empty string")
    if compact_column in participating_columns:
        raise ValueError(
            f"codec_intent.compact_column {compact_column!r} must not also be "
            "a participating column"
        )
    separator = codec_intent.get("separator")
    if not isinstance(separator, str) or separator == "":
        raise ValueError("codec_intent.separator must be a non-empty string")
    absent_value = codec_intent.get("absent_value")
    if not isinstance(absent_value, str) or absent_value == "":
        raise ValueError("codec_intent.absent_value must be a non-empty string")
    # No-escaping grammar soundness: encode joins tokens (real values or the
    # absent marker) with the separator; decode splits on the exact separator.
    # If either marker contains the other, a run of marker/separator characters
    # re-splits ambiguously (e.g. separator "--", absent "-", values
    # ["A", "", "B"] encode to "A-----B", which decode splits into an empty
    # token). Rejecting overlap in *either* direction guarantees that no token
    # contains the separator and none is empty, so every accepted encode output
    # decodes back to the same tokens under the identical intent. Real values
    # containing the separator or equal to the absent marker are rejected per
    # row in _encode_compact_value, so no further ordinary join/split ambiguity
    # remains in this grammar.
    if separator in absent_value or absent_value in separator:
        raise ValueError(
            f"codec_intent.separator {separator!r} and absent_value "
            f"{absent_value!r} must not overlap (neither may contain the "
            "other); an overlapping no-escaping grammar can encode values that "
            "cannot be decoded unambiguously"
        )
    return {
        "participating_columns": participating_columns,
        "compact_column": compact_column,
        "separator": separator,
        "absent_value": absent_value,
    }


def _encode_compact_value(
    row: pd.Series,
    *,
    participating_columns: list[Any],
    separator: str,
    absent_value: str,
) -> str:
    tokens: list[str] = []
    for column in participating_columns:
        raw_value = row[column]
        if _is_empty_cell(raw_value):
            tokens.append(absent_value)
            continue
        if not isinstance(raw_value, str):
            raise ValueError(
                f"participating column {column!r} contains non-string value "
                f"{raw_value!r}; Cell Codec is string-oriented "
                "(ADR-VISIBLE-CELL-TYPING-STRING-SUBSTRATE) and typed values "
                "would silently change type through the compact-cell roundtrip"
            )
        token = raw_value
        if token == absent_value:
            raise ValueError(
                f"participating column {column!r} uses absent-value marker "
                f"{absent_value!r} as a real value"
            )
        if separator in token:
            raise ValueError(
                f"participating column {column!r} contains codec separator {separator!r}"
            )
        tokens.append(token)
    return separator.join(tokens)


def _decode_compact_value(
    value: Any,
    *,
    participating_columns: list[Any],
    separator: str,
    absent_value: str,
) -> dict[Any, Any]:
    text = "" if _is_empty_cell(value) else str(value)
    tokens = text.split(separator)
    if len(tokens) != len(participating_columns):
        raise ValueError(
            "compact value token count does not match participating columns: "
            f"expected {len(participating_columns)}, got {len(tokens)}"
        )

    decoded: dict[Any, Any] = {}
    for column, token in zip(participating_columns, tokens):
        if token == "":
            raise ValueError(f"compact value contains empty token for column {column!r}")
        decoded[column] = "" if token == absent_value else token
    return decoded


def _reject_helper_participating_columns(
    frames: Mapping[str, Any],
    frame_name: str,
    participating_columns: list[Any],
) -> None:
    helper_columns = _helper_columns_for_frame(_meta_from_frames(frames), frame_name)
    rejected = [column for column in participating_columns if column in helper_columns]
    if rejected:
        raise ValueError(
            "helper or derived columns must not participate in Cell Codec "
            f"contraction by default: {rejected!r}"
        )


def _helper_columns_for_frame(meta: Mapping[str, Any], frame_name: str) -> set[Any]:
    helper_columns: set[Any] = set()

    sheets = meta.get("sheets")
    if isinstance(sheets, Mapping):
        sheet_meta = sheets.get(frame_name)
        if isinstance(sheet_meta, Mapping):
            helper_columns.update(_column_name_set(sheet_meta.get("helper_columns")))

    derived = meta.get("derived")
    if isinstance(derived, Mapping):
        derived_sheets = derived.get("sheets")
        if isinstance(derived_sheets, Mapping):
            sheet_meta = derived_sheets.get(frame_name)
            if isinstance(sheet_meta, Mapping):
                helper_columns.update(_column_name_set(sheet_meta.get("helper_columns")))
                enrich_lookup = sheet_meta.get("enrich_lookup")
                if isinstance(enrich_lookup, Mapping):
                    helper_columns.update(_column_name_set(enrich_lookup.get("helper_columns")))

    return helper_columns


def _column_name_set(value: Any) -> set[Any]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        return set(value)
    if isinstance(value, Iterable):
        return set(value)
    return set()
