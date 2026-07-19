"""Shared leaf primitives for the ``xref_crosstable`` package.

Decouples ``operation`` and ``dense_axes`` so the package no longer has a
load-time import cycle. Bodies are verbatim moves out of the original flat
module; only their location has changed.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain._cell_primitives import _values_equal

_META_KEY = "xref_crosstable"


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


def _ensure_unique_physical_labels(df: pd.DataFrame, *, frame_name: str) -> None:
    """Reject duplicate physical column labels with a contract diagnostic.

    Duplicate labels make positional indexing non-scalar (``row[label]``
    yields a ``Series``), so any duplicated physical field would corrupt
    cell values silently. Equality-based detection deliberately avoids
    hashing so unusual labels still get the XRef diagnostic instead of a
    raw pandas ``TypeError``.
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


def _ensure_unique_field_list(values: Iterable[Any], field_name: str) -> None:
    """Reject duplicate entries in a configured field list (e.g. row_keys)."""
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


def _ensure_column_identity_values(values: Iterable[Any], source_label: str) -> None:
    """Enforce the carrier-stable XRef column-identity contract on values.

    XRef matrix column identities that participate in the persisted
    matrix/relation roundtrip must be non-empty strings: spreadsheet
    carriers realize matrix headers as strings, so numeric, missing
    (``None``/``NaN``/``NA``), mixed-type, or unhashable identities would
    silently change type, collide, or produce non-scalar cells on the way
    back. Duplicates are allowed here (relation rows repeat identities);
    use :func:`_ensure_column_identity_list` for identity lists.
    """
    invalid_reprs: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            continue
        value_repr = repr(value)
        if value_repr not in invalid_reprs:
            invalid_reprs.append(value_repr)
    if invalid_reprs:
        raise ValueError(
            f"{source_label} must contain non-empty string column "
            f"identities; invalid value(s): [{', '.join(invalid_reprs)}]. "
            "Numeric, missing, or mixed-type identities are not stable "
            "across spreadsheet headers."
        )


def _ensure_column_identity_list(values: Iterable[Any], source_label: str) -> None:
    """Enforce the identity contract plus uniqueness on an identity list."""
    materialized = list(values)
    _ensure_column_identity_values(materialized, source_label)
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in materialized:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise ValueError(
            f"{source_label} contains duplicate column identit(y/ies): "
            f"{duplicates!r}; matrix column identities must be unique"
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


def _ordered_values_equal(left: Iterable[Any], right: Iterable[Any]) -> bool:
    left_values = list(left)
    right_values = list(right)
    return len(left_values) == len(right_values) and all(
        _values_equal(left_value, right_value)
        for left_value, right_value in zip(left_values, right_values, strict=True)
    )


def _xref_config(
    frames: Mapping[str, Any],
    *config_ids: str,
    relation: str | None = None,
    matrix: str | None = None,
) -> Mapping[str, Any] | None:
    """Find the intent entry for a transform id or a relation/matrix frame.

    Exact config-id match wins. The fallback matches the persisted
    ``relation`` / ``matrix`` frame-identity fields; more than one matching
    entry is ambiguous intent and fails explicitly rather than silently
    picking the first entry.
    """
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

    matches: list[tuple[Any, Mapping[str, Any]]] = []
    for key, config in configs.items():
        if not isinstance(config, Mapping):
            continue
        if (relation is not None and config.get("relation") == relation) or (
            matrix is not None and config.get("matrix") == matrix
        ):
            matches.append((key, config))
    if len(matches) > 1:
        match_names = [key for key, _ in matches]
        raise ValueError(
            f"Ambiguous xref_crosstable metadata for "
            f"relation={relation!r} / matrix={matrix!r}: entries "
            f"{match_names!r} both match. Name the intended transform "
            "explicitly (name=...) to disambiguate."
        )
    if matches:
        return matches[0][1]
    return None
