"""Pure forward/inverse grouped-header projection primitives for GX-1.

* :func:`build_grouped_header` (forward) classifies a flat canonical-string
  matrix's columns and, for each dynamic column, resolves its exact visible
  label tuple through an already-resolved :class:`ResolvedAxisMapping`.
* :func:`restore_flat_matrix` (inverse) treats the descriptor as the
  authoritative visible-header identity source and reconstructs the exact flat
  canonical matrix, mapping each visible tuple back to its canonical key.

Both primitives are pure and backend-neutral: they consume an already-resolved
mapping (they never call ``resolve_axis_mapping``), never touch carriers,
rendering, the pipeline registry, or ``_meta``, and are build-then-return. The
Slice 1 resolver owns the key/label bijection; these primitives do not repeat
it. The flat DataFrame is kept separate from the descriptor.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from ..xref_axis_mapping import ResolvedAxisMapping

from .model import (
    DynamicColumn,
    GroupedHeader,
    GroupedHeaderError,
    RowKeyColumn,
    _require_non_empty_string,
    _unsupported_type_detail,
)

_MATRIX_LABEL = "grouped matrix frame"


def _require_dataframe(frame: Any) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise GroupedHeaderError(
            f"{_MATRIX_LABEL} must be a pandas DataFrame"
        )
    return frame


def _require_mapping(mapping: Any) -> ResolvedAxisMapping:
    if type(mapping) is not ResolvedAxisMapping:
        raise GroupedHeaderError(
            "mapping must be an already-resolved ResolvedAxisMapping"
        )
    return mapping


def _declared_row_keys(row_keys: str | Iterable[Any]) -> tuple[str, ...]:
    if isinstance(row_keys, str):
        declared: tuple[Any, ...] = (row_keys,)
    elif isinstance(row_keys, (bytes, bytearray)):
        raise GroupedHeaderError("row_keys must be a string or a sequence of strings")
    else:
        try:
            declared = tuple(row_keys)
        except TypeError:
            raise GroupedHeaderError(
                "row_keys must be a string or a sequence of strings"
            ) from None
    if not declared:
        raise GroupedHeaderError("row_keys must declare at least one row-key column")
    owned = tuple(
        _require_non_empty_string(value, field_name=f"row_keys[{index}]")
        for index, value in enumerate(declared)
    )
    seen: set[str] = set()
    for value in owned:
        if value in seen:
            raise GroupedHeaderError(
                f"row_keys contains duplicate row-key declaration {value!r}"
            )
        seen.add(value)
    return owned


def _resolve_level_names(
    mapping: ResolvedAxisMapping,
    level_names: Iterable[str] | None,
) -> tuple[str, ...]:
    if level_names is None:
        return mapping.label_columns
    if isinstance(level_names, (str, bytes)):
        raise GroupedHeaderError("level_names must be an ordered sequence of names")
    resolved = tuple(level_names)
    if len(resolved) != mapping.label_arity:
        raise GroupedHeaderError(
            f"level_names must have one name per level; got {len(resolved)}, "
            f"expected {mapping.label_arity}"
        )
    return resolved


def _require_dynamic_header(label: Any, *, position: int) -> str:
    if type(label) is not str:
        raise GroupedHeaderError(
            f"{_MATRIX_LABEL} physical column at position {position} is not a "
            "declared row key and must be an exact non-empty string canonical "
            f"header; got {_unsupported_type_detail()}"
        )
    if not str.strip(label):
        raise GroupedHeaderError(
            f"{_MATRIX_LABEL} physical column at position {position} must be an "
            "exact non-empty string canonical header"
        )
    return label


def _string_labels(physical_labels: list[Any]) -> frozenset[str]:
    """Collect the exact-string physical labels safely (no hostile comparison)."""
    return frozenset(label for label in physical_labels if type(label) is str)


def _classify_columns(
    physical_labels: list[Any],
    *,
    row_key_set: frozenset[str],
    mapping: ResolvedAxisMapping,
) -> tuple[RowKeyColumn | DynamicColumn, ...]:
    columns: list[RowKeyColumn | DynamicColumn] = []
    seen_strings: set[str] = set()
    for position, label in enumerate(physical_labels):
        if type(label) is str:
            if label in seen_strings:
                raise GroupedHeaderError(
                    f"{_MATRIX_LABEL} has duplicate physical column {label!r}; "
                    "matrix columns must be unique"
                )
            seen_strings.add(label)
        if type(label) is str and label in row_key_set:
            columns.append(RowKeyColumn(label=label, position=position))
            continue
        header = _require_dynamic_header(label, position=position)
        columns.append(
            DynamicColumn(labels=mapping.labels_for_key(header), position=position)
        )
    return tuple(columns)


def build_grouped_header(
    frame: pd.DataFrame,
    *,
    row_keys: str | Iterable[Any],
    mapping: ResolvedAxisMapping,
    level_names: Iterable[str] | None = None,
) -> GroupedHeader:
    """Forward: project a flat canonical matrix into a grouped-header descriptor.

    Declared ``row_keys`` become single-level :class:`RowKeyColumn` entries;
    every other physical column is dynamic and its exact non-empty string
    canonical header is resolved to its visible label tuple via the mapping.
    Physical column order and positions are preserved. The DataFrame is neither
    mutated nor transformed; the descriptor is built fully before returning.
    """
    _require_dataframe(frame)
    _require_mapping(mapping)
    if isinstance(frame.columns, pd.MultiIndex):
        raise GroupedHeaderError(
            f"{_MATRIX_LABEL} must have flat column labels; got a MultiIndex"
        )
    physical_labels = list(frame.columns)
    if any(isinstance(label, tuple) for label in physical_labels):
        raise GroupedHeaderError(
            f"{_MATRIX_LABEL} must have flat column labels; got tuple-valued label(s)"
        )
    row_key_cols = _declared_row_keys(row_keys)
    present = _string_labels(physical_labels)
    missing = [key for key in row_key_cols if key not in present]
    if missing:
        raise GroupedHeaderError(
            f"{_MATRIX_LABEL} is missing declared row-key column(s) {missing!r}"
        )
    resolved_levels = _resolve_level_names(mapping, level_names)
    columns = _classify_columns(
        physical_labels,
        row_key_set=frozenset(row_key_cols),
        mapping=mapping,
    )
    return GroupedHeader(level_names=resolved_levels, columns=columns)


def restore_flat_matrix(
    frame: pd.DataFrame,
    header: GroupedHeader,
    *,
    mapping: ResolvedAxisMapping,
) -> pd.DataFrame:
    """Inverse: reconstruct the exact flat canonical matrix from the descriptor.

    The descriptor is the authoritative visible-header identity source: each
    :class:`DynamicColumn` visible tuple is resolved back to its canonical key
    via the mapping, and each :class:`RowKeyColumn` keeps its physical label.
    Data, index, row order, and physical column order are preserved; the input
    frame is never mutated. The full output-column sequence is built before the
    result frame is created.
    """
    _require_dataframe(frame)
    _require_mapping(mapping)
    if type(header) is not GroupedHeader:
        raise GroupedHeaderError("header must be a GroupedHeader descriptor")
    if len(header.columns) != frame.shape[1]:
        raise GroupedHeaderError(
            "grouped header describes "
            f"{len(header.columns)} column(s) but the frame has {frame.shape[1]}"
        )
    new_labels: list[str] = []
    seen: set[str] = set()
    for column in header.columns:
        if type(column) is RowKeyColumn:
            restored = column.label
        else:
            restored = mapping.key_for_labels(column.labels)
        if restored in seen:
            raise GroupedHeaderError(
                f"restore produced duplicate physical column label {restored!r}; "
                "matrix columns must be unique"
            )
        seen.add(restored)
        new_labels.append(restored)
    result = frame.copy()
    result.columns = pd.Index(new_labels)
    return result


__all__ = [
    "build_grouped_header",
    "restore_flat_matrix",
]
