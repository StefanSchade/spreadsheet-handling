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


def _is_missing_like(value: Any) -> bool:
    """True for a scalar missing label (``None`` / ``NaN`` / ``pd.NA``).

    Array-like labels (tuples, ndarrays) are not scalar missing values and
    return ``False`` here; their addressability is checked separately by
    :func:`_has_deterministic_equality`.
    """
    if value is None:
        return True
    if not pd.api.types.is_scalar(value):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _has_deterministic_equality(value: Any) -> bool:
    """True when ``value == value`` yields an unambiguous boolean.

    A label whose self-comparison is ambiguous (e.g. a multi-element
    ndarray, whose ``==`` yields an array) cannot be de-duplicated or
    addressed as a scalar column.
    """
    try:
        return bool(value == value)
    except (TypeError, ValueError):
        return False


def _is_hashable(value: Any) -> bool:
    """True when ``value`` can be hashed.

    pandas addresses a column label through a hash lookup, so an unhashable
    label (e.g. a Python ``list``) cannot be selected as a scalar column and
    would raise a raw ``TypeError`` inside membership/selection. A hashable
    tuple label stays valid.
    """
    try:
        hash(value)
    except TypeError:
        return False
    return True


def _ensure_unique_physical_labels(df: pd.DataFrame, *, frame_name: str) -> None:
    """Reject physical column labels that cannot address a scalar field.

    This is the physical-frame column-label boundary, distinct from the
    matrix-axis identity contract (:func:`_ensure_column_identity_values`).
    Physical labels are *not* required to be strings: numeric or tuple
    labels are permitted when they are non-missing, unique, deterministically
    comparable, and scalar-addressable. They must be:

    * non-missing -- a missing label (``None`` / ``NaN`` / ``pd.NA``) cannot
      address a scalar column and is not even equal to itself (``NaN``) or
      unambiguously comparable (``pd.NA``);
    * deterministically comparable -- a label whose equality yields an
      ambiguous truth value (e.g. a multi-element ndarray) cannot be
      de-duplicated or addressed;
    * hashable -- pandas addresses a column label through a hash lookup, so
      an unhashable label (e.g. a Python ``list``) cannot be selected and
      would raise a raw ``TypeError`` inside membership/selection;
    * unique -- duplicate labels make ``row[label]`` yield a ``Series``
      instead of a scalar, silently corrupting cell values.

    Validation runs before any pandas selection, equality-based membership,
    metadata write, or cleanup scheduling.
    """
    labels = df.columns.tolist()
    missing = [label for label in labels if _is_missing_like(label)]
    if missing:
        raise ValueError(
            f"Frame {frame_name!r} has missing-like physical column label(s) "
            f"{missing!r}; physical labels must be non-missing to address a "
            "scalar column"
        )
    ambiguous = [label for label in labels if not _has_deterministic_equality(label)]
    if ambiguous:
        raise ValueError(
            f"Frame {frame_name!r} has physical column label(s) with ambiguous "
            f"equality {ambiguous!r}; physical labels must be deterministically "
            "comparable to address a scalar column"
        )
    unhashable = [label for label in labels if not _is_hashable(label)]
    if unhashable:
        raise ValueError(
            f"Frame {frame_name!r} has unhashable physical column label(s) "
            f"{unhashable!r}; physical labels must be hashable to address a "
            "scalar column"
        )
    # Every remaining label compares with an unambiguous boolean, so this
    # equality-based duplicate detection is safe and stays non-hashing so
    # valid tuple labels are not rejected for being unhashable-by-value.
    duplicates: list[Any] = []
    seen: list[Any] = []
    for label in labels:
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
