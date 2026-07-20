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

from .scalar import parse_cell_value, serialize_cell_value

Frames = dict[str, Any]


def decode_cell_values(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    codec_intent: Mapping[str, Any] | None = None,
    value: str = "value",
    code: str = "code",
    passthrough_columns: Iterable[Any] | None = None,
    drop_empty: bool = True,
    mode: str | None = None,
    delimiter: str = "-",
    allowed_codes: Iterable[Any] | None = None,
    allowed_tokens: Iterable[Any] | None = None,
    allowed_from_legend: str | None = None,
    normalize_case: str | None = None,
    strip: bool = False,
    name: str | None = None,
) -> Frames:
    """Decode a compact column using explicit codec intent.

    Historical code/token mode remains available only when ``mode`` is passed
    explicitly by current composition callers.
    """
    if codec_intent is not None:
        return _decode_position_based(
            frames,
            source=source,
            output=output,
            codec_intent=codec_intent,
            name=name,
        )
    if mode is None:
        raise ValueError("codec intent is required for decoding compact cell values")
    return _decode_legacy_code_rows(
        frames,
        source=source,
        output=output,
        value=value,
        code=code,
        passthrough_columns=passthrough_columns,
        drop_empty=drop_empty,
        mode=mode,
        delimiter=delimiter,
        allowed_codes=allowed_codes,
        allowed_tokens=allowed_tokens,
        allowed_from_legend=allowed_from_legend,
        normalize_case=normalize_case,
        strip=strip,
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
    return out


def encode_cell_values(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str,
    codec_intent: Mapping[str, Any] | None = None,
    group_by: str | Iterable[Any] | None = None,
    code: str = "code",
    value: str = "value",
    mode: str | None = None,
    delimiter: str = "-",
    allowed_codes: Iterable[Any] | None = None,
    allowed_tokens: Iterable[Any] | None = None,
    allowed_from_legend: str | None = None,
    canonical_order: Iterable[Any] | None = None,
    normalize_case: str | None = None,
    strip: bool = False,
    name: str | None = None,
) -> Frames:
    """Encode configured slot columns into a compact column.

    Historical code/token mode remains available only when ``mode`` is passed
    explicitly by current composition callers.
    """
    if codec_intent is not None:
        return _encode_position_based(
            frames,
            source=source,
            output=output,
            codec_intent=codec_intent,
            name=name,
        )
    if mode is None:
        raise ValueError("codec intent is required for encoding compact cell values")
    if group_by is None:
        raise ValueError("group_by is required for legacy code-row encoding")
    return _encode_legacy_code_rows(
        frames,
        source=source,
        output=output,
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
    _ensure_unique_field_list(group_cols, "group_by")
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


def _ensure_unique_physical_labels(df: pd.DataFrame, *, frame_name: str) -> None:
    """Reject duplicate physical column labels with a codec diagnostic.

    Duplicate labels make ``row[label]`` indexing non-scalar (a ``Series``),
    which would corrupt encoded/decoded cell values silently. Equality-based
    detection avoids hashing so unusual labels still get the deterministic
    diagnostic instead of raw pandas behavior.
    """
    duplicates: list[Any] = []
    seen: list[Any] = []
    for label in df.columns.tolist():
        if any(_values_equal(label, existing) for existing in seen):
            if not any(_values_equal(label, existing) for existing in duplicates):
                duplicates.append(label)
        else:
            seen.append(label)
    if duplicates:
        raise ValueError(
            f"Frame {frame_name!r} has duplicate physical column label(s) "
            f"{duplicates!r}; duplicate columns cannot be addressed as "
            "scalar fields"
        )


def _ensure_unique_field_list(values: list[Any], field_name: str) -> None:
    """Reject duplicate entries in a configured field list."""
    duplicates: list[Any] = []
    seen: list[Any] = []
    for value in values:
        if any(_values_equal(value, existing) for existing in seen):
            if not any(_values_equal(value, existing) for existing in duplicates):
                duplicates.append(value)
        else:
            seen.append(value)
    if duplicates:
        raise ValueError(
            f"{field_name} contains duplicate field(s) {duplicates!r}; "
            "configured fields must be unique"
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
    _ensure_unique_field_list(participating_columns, "codec_intent.participating_columns")
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
    if separator in absent_value:
        raise ValueError(
            f"codec_intent.absent_value {absent_value!r} must not contain the "
            f"separator {separator!r}"
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
