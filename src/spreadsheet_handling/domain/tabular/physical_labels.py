"""Physical frame column-label safety boundary.

The shared physical table-boundary contract for domain transformations:

    Physical frame column labels used by domain transformations must be
    non-missing, hashable, uniquely and deterministically comparable, and
    safe for scalar pandas addressing.

This is deliberately *distinct* from family-specific value contracts:

* XRef matrix-axis identities remain unique, non-empty strings;
* Cell Codec participating cell values remain string-oriented;
* family-specific field-role and collision rules stay in their families;
* future Tuple/MultiIndex and stable-id/display-label design is untouched.

The helpers here validate *before* any pandas membership, selection,
grouping, or row indexing, so an invalid label yields a deterministic
domain diagnostic rather than a raw pandas/Python exception (a
``TypeError: unhashable type``, ambiguous-truth ``ValueError``, or a
non-scalar ``Series`` produced by duplicate labels).

The implementation stays small and explicit; it introduces no generic
arbitrary-object equality framework, table abstraction, or serialization
layer.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from spreadsheet_handling.domain._cell_primitives import _values_equal


def _is_missing_like(value: Any) -> bool:
    """True for a scalar missing label (``None`` / ``NaN`` / ``pd.NA``).

    Array-like labels (tuples, ndarrays) are not scalar missing values and
    return ``False`` here; their addressability is checked separately.
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


def is_scalar_addressable_label(value: Any) -> bool:
    """True when a single label is non-missing, deterministic, and hashable.

    A convenience predicate for callers that need to check one label without
    raising; :func:`ensure_unique_physical_column_labels` is the frame-level
    boundary that additionally enforces uniqueness.
    """
    return (
        not _is_missing_like(value)
        and _has_deterministic_equality(value)
        and _is_hashable(value)
    )


def ensure_unique_physical_column_labels(
    frame: pd.DataFrame,
    *,
    frame_name: str,
) -> None:
    """Reject physical column labels that cannot address a scalar field.

    This is the physical-frame column-label boundary. Physical labels are
    *not* required to be strings: numeric or hashable tuple labels are
    permitted when they are non-missing, unique, deterministically
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
    grouping, row indexing, metadata write, or cleanup scheduling.
    """
    labels = frame.columns.tolist()
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


def ensure_unique_field_declaration(
    values: Iterable[Any],
    *,
    field_name: str,
) -> None:
    """Reject duplicate entries in a configured field list.

    Used for configured selectors such as ``row_keys``, ``group_by``, and
    ``participating_columns`` where a repeated declaration would silently
    address or emit the same physical column twice. Detection is
    equality-based (non-hashing) so it stays safe for the same label
    categories as the physical-label boundary.
    """
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
