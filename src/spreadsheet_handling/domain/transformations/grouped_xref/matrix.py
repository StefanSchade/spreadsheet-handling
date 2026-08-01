"""Feature-owned Frames-boundary carrier for the grouped-XRef composites (GX-2).

GX-2 of ``FTR-XREF-AXIS-MAPPINGS-P4A2`` (merged grouped-XRef capability). A
:class:`GroupedMatrix` bundles the flat canonical-string matrix DataFrame and its
:class:`GroupedHeader` descriptor as a *single* Frames value. Raw construction
is deliberately unavailable: public callers and future workbook carriers enter
through :func:`grouped_matrix_from_canonical`, which proves that the current
canonical flat column schema projects to the exact carried descriptor under a
live resolved mapping. The inverse repeats that proof before restoration, so
later DataFrame column mutation cannot revive GX1-A-M2 mispairing.

The carrier is deliberately *not* a value object. It holds a mutable pandas
DataFrame, exactly as a Frames mapping already holds mutable DataFrames as its
values, so it uses identity semantics (``eq=False``) and does not claim
value-equality. It never copies the frame to feign immutability, stores nothing
in ``_meta``, builds no ``MultiIndex``, and persists no mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from spreadsheet_handling.core.exact_table import ExactTable

from ..xref_axis_mapping import ResolvedAxisMapping

from .model import GroupedHeader, RowKeyColumn
from .projection import build_grouped_header


class GroupedXrefError(ValueError):
    """A deliberate diagnostic raised by the grouped-XRef composites (GX-2).

    Used only for composite-owned structural and public-input failures. Domain
    failures keep their own error types: resolver failures stay
    ``AxisMappingError``, grouped-header failures stay ``GroupedHeaderError``,
    and XRef failures stay XRef ``ValueError`` s.
    """


@dataclass(frozen=True, eq=False, init=False)
class GroupedMatrix:
    """Opaque carrier of a flat canonical matrix plus its grouped descriptor.

    ``frame`` is a flat, canonical-string-headed matrix; ``header`` is the
    immutable GX-1 :class:`GroupedHeader` describing its dynamic columns'
    visible label tuples. Use :func:`grouped_matrix_from_canonical` to construct
    a validated pair. Direct construction is rejected deliberately.

    Identity semantics: two carriers with equal content are *not* equal; the
    carrier is not a hashable *value* object. ``frozen=True`` only prevents
    rebinding the two references; it makes no false immutability claim about the
    contained DataFrame.
    """

    frame: pd.DataFrame
    header: GroupedHeader

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise GroupedXrefError(
            "GroupedMatrix cannot be constructed directly; use "
            "grouped_matrix_from_canonical"
        )

    @classmethod
    def _from_validated_pair(
        cls,
        frame: pd.DataFrame,
        header: GroupedHeader,
    ) -> GroupedMatrix:
        """Build after the feature-owned exact-pair validator has succeeded."""
        grouped = object.__new__(cls)
        object.__setattr__(grouped, "frame", frame)
        object.__setattr__(grouped, "header", header)
        return grouped


def _require_pair_components(
    frame: Any,
    header: Any,
) -> tuple[pd.DataFrame, GroupedHeader]:
    if not isinstance(frame, pd.DataFrame):
        raise GroupedXrefError("GroupedMatrix.frame must be a pandas DataFrame")
    if type(header) is not GroupedHeader:
        raise GroupedXrefError(
            "GroupedMatrix.header must be a GroupedHeader descriptor"
        )
    return frame, header


def _validate_canonical_pair(
    frame: Any,
    header: Any,
    *,
    mapping: ResolvedAxisMapping,
) -> tuple[pd.DataFrame, GroupedHeader]:
    """Prove the current canonical frame projects to exactly ``header``.

    Accepted GX-1 owns canonical-frame and mapping validation. GX-2 owns only
    the final pair-equality diagnostic: two individually valid values that do
    not describe the same physical column identities and positions.
    """
    canonical, descriptor = _require_pair_components(frame, header)
    row_keys = tuple(
        column.label
        for column in descriptor.columns
        if type(column) is RowKeyColumn
    )
    derived = build_grouped_header(
        canonical,
        row_keys=row_keys,
        mapping=mapping,
        level_names=descriptor.level_names,
    )
    if derived != descriptor:
        raise GroupedXrefError(
            "GroupedMatrix frame/header pairing does not match the canonical "
            "frame under the resolved mapping"
        )
    return canonical, descriptor


def grouped_matrix_from_canonical(
    frame: pd.DataFrame,
    header: GroupedHeader,
    *,
    mapping: ResolvedAxisMapping,
) -> GroupedMatrix:
    """Construct a carrier from an exact canonical flat frame/header pair.

    This is the public construction seam for grouped composites and future
    GX-3/GX-4 readback. Workbook carriers must first reconstruct canonical flat
    headers from exact visible tuples and the live mapping; no mapping or
    fingerprint is persisted in the carrier.
    """
    canonical, descriptor = _validate_canonical_pair(
        frame,
        header,
        mapping=mapping,
    )
    return GroupedMatrix._from_validated_pair(canonical, descriptor)


def _validate_grouped_matrix_pair(
    grouped: GroupedMatrix,
    *,
    mapping: ResolvedAxisMapping,
) -> None:
    """Revalidate a carrier immediately before inverse restoration."""
    _validate_canonical_pair(grouped.frame, grouped.header, mapping=mapping)


def grouped_matrix_to_exact_table(matrix: GroupedMatrix) -> ExactTable:
    """Project a grouped matrix into a backend-neutral exact table (GX-3b forward).

    The visible label tuples are read authoritatively from the carrier's
    :class:`GroupedHeader` (they already live there), so no mapping is needed to
    render. Row-key columns show their leaf label with blank upper cells; dynamic
    columns show one visible label component per level (repeated literal labels,
    never merges). Canonical dynamic keys are never rendered -- only
    ``matrix.frame`` values become the data block, in physical column order.

    Structural revalidation (no mapping): the carried frame width must still match
    the grouped header, catching a post-construction column mutation.
    """
    if type(matrix) is not GroupedMatrix:
        raise GroupedXrefError(
            "grouped_matrix_to_exact_table requires a GroupedMatrix carrier"
        )
    header = matrix.header
    frame = matrix.frame
    n_cols = len(header.columns)
    if frame.shape[1] != n_cols:
        raise GroupedXrefError(
            "GroupedMatrix frame width does not match its grouped header; "
            f"frame has {frame.shape[1]} column(s), header describes {n_cols}"
        )
    depth = header.arity
    leaf_level = depth - 1
    grid: list[tuple[str, ...]] = []
    for level in range(depth):
        row: list[str] = []
        for column in header.columns:
            if type(column) is RowKeyColumn:
                row.append(column.label if level == leaf_level else "")
            else:
                row.append(column.labels[level])
        grid.append(tuple(row))
    data = tuple(tuple(record) for record in frame.values.tolist())
    return ExactTable(
        header_grid=tuple(grid),
        data=data,
        header_rows=depth,
        n_cols=n_cols,
    )


__all__ = [
    "GroupedMatrix",
    "GroupedXrefError",
    "grouped_matrix_from_canonical",
    "grouped_matrix_to_exact_table",
]
