"""Grouped-XRef reverse reconstruction step (GX-3b).

GX-3b of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. One backend-neutral ``Frames -> Frames``
step turns a parsed exact table (a :class:`~spreadsheet_handling.core.exact_table.ExactTable`,
exported by generic workbook projection under the GX-3a opt-in read gate) into a
validated :class:`GroupedMatrix`, resolving exactly one live axis mapping.

It ends at ``GroupedMatrix``; the unchanged ``expand_grouped_xref`` performs the
canonical relation expansion afterward. This step wraps no XRef call, writes no
metadata, builds no ``MultiIndex``, and performs no delimiter join/split. Row-key
columns are identified explicitly by their leaf-row label (not by blank shape);
merge-repeat blanks in dynamic columns are normalised through the accepted GX-3a
``forward_fill_header_grid`` helper, skipping the declared row-key columns.

Publication is atomic: the flat frame, header, and carrier are built fully before
the output is placed into a copied Frames mapping, so any failure leaves caller
Frames and ``_meta`` unchanged.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.core.exact_table import ExactTable
from spreadsheet_handling.core.header_grid import forward_fill_header_grid

from ..xref_axis_mapping import (
    AxisMappingIntent,
    AxisOrderPolicy,
    ResolvedAxisMapping,
    resolve_axis_mapping,
)

from .matrix import GroupedXrefError, grouped_matrix_from_canonical
from .projection import build_grouped_header

Frames = dict[str, Any]


def _require_frames(frames: Any) -> Mapping[str, Any]:
    if not isinstance(frames, Mapping):
        raise GroupedXrefError("Grouped XRef frames must be a mapping")
    return frames


def _require_name(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise GroupedXrefError(f"{field_name} must be a non-empty string")
    return value


def _order_policy(value: Any) -> AxisOrderPolicy:
    if type(value) is AxisOrderPolicy:
        return value
    if type(value) is str:
        try:
            return AxisOrderPolicy(value)
        except ValueError:
            pass
    raise GroupedXrefError(
        "order_policy must be 'source_row' or 'columns' "
        "(or an AxisOrderPolicy member)"
    )


def _build_intent(
    *,
    source_frame: str,
    key_column: str,
    label_columns: Iterable[str],
    order_policy: Any,
    order_columns: Iterable[Any],
) -> AxisMappingIntent:
    # The resolver owns every value-level validation; this step only maps a raw
    # iterable into the tuple the frozen intent expects.
    if isinstance(label_columns, (str, bytes)):
        raise GroupedXrefError(
            "label_columns must be an ordered sequence of source label columns"
        )
    try:
        owned_labels = tuple(label_columns)
    except TypeError:
        raise GroupedXrefError(
            "label_columns must be an ordered sequence of source label columns"
        ) from None
    return AxisMappingIntent(
        source_frame=source_frame,
        key_column=key_column,
        label_columns=owned_labels,
        order_policy=_order_policy(order_policy),
        order_columns=order_columns,
    )


def _owned_row_keys(row_keys: str | Iterable[Any]) -> tuple[str, ...]:
    if isinstance(row_keys, str):
        declared: tuple[Any, ...] = (row_keys,)
    elif isinstance(row_keys, (bytes, bytearray)):
        raise GroupedXrefError("row_keys must be a string or a sequence of strings")
    else:
        try:
            declared = tuple(row_keys)
        except TypeError:
            raise GroupedXrefError(
                "row_keys must be a string or a sequence of strings"
            ) from None
    if not declared:
        raise GroupedXrefError("row_keys must declare at least one row-key column")
    owned: list[str] = []
    seen: set[str] = set()
    for value in declared:
        name = _require_name(value, field_name="row_keys entry")
        if name in seen:
            raise GroupedXrefError(f"row_keys contains duplicate declaration {name!r}")
        seen.add(name)
        owned.append(name)
    return tuple(owned)


def _require_exact_table(value: Any, *, table: str) -> ExactTable:
    if type(value) is not ExactTable:
        raise GroupedXrefError(
            f"Grouped reconstruction input frame {table!r} must be an ExactTable "
            "produced by exact-mode workbook projection"
        )
    return value


def _validated_geometry(exact: ExactTable, *, depth: int) -> None:
    """Reject non-rectangular geometry and a header depth mismatch."""
    grid = exact.header_grid
    if len(grid) != exact.header_rows:
        raise GroupedXrefError(
            "Exact table header_rows does not match its header grid; "
            f"header_rows={exact.header_rows}, grid rows={len(grid)}"
        )
    if exact.header_rows != depth:
        raise GroupedXrefError(
            "Exact table header depth does not match label_columns; "
            f"grid depth {exact.header_rows}, expected {depth}"
        )
    for row in grid:
        if len(row) != exact.n_cols:
            raise GroupedXrefError(
                "Exact table header grid is not rectangular; "
                f"expected width {exact.n_cols}"
            )
    for record in exact.data:
        if len(record) != exact.n_cols:
            raise GroupedXrefError(
                "Exact table data row width does not match column count; "
                f"expected {exact.n_cols}"
            )


def _row_key_positions(
    exact: ExactTable,
    *,
    row_keys: tuple[str, ...],
) -> dict[str, int]:
    """Match each declared row key to exactly one physical column by leaf label."""
    leaf_row = exact.header_grid[-1]
    positions: dict[str, int] = {}
    for name in row_keys:
        matches = [index for index, label in enumerate(leaf_row) if label == name]
        if not matches:
            raise GroupedXrefError(
                f"Declared row-key column {name!r} was not found in the leaf header row"
            )
        if len(matches) > 1:
            raise GroupedXrefError(
                f"Declared row-key column {name!r} matches multiple physical columns "
                f"at positions {matches!r}"
            )
        positions[name] = matches[0]
    return positions


def _require_blank_row_key_uppers(
    exact: ExactTable,
    *,
    row_key_positions: Mapping[str, int],
) -> None:
    """A single-level row-key column must have blank upper header cells."""
    for name, position in row_key_positions.items():
        for level in range(exact.header_rows - 1):
            if exact.header_grid[level][position] != "":
                raise GroupedXrefError(
                    f"Row-key column {name!r} has a non-blank upper header cell at "
                    f"level {level}; row-key columns must be single-level"
                )


def _canonical_labels(
    exact: ExactTable,
    *,
    row_key_positions: Mapping[str, int],
    mapping: ResolvedAxisMapping,
) -> list[str]:
    """Resolve each physical column to its canonical flat label (physical order)."""
    position_to_row_key = {position: name for name, position in row_key_positions.items()}
    filled = forward_fill_header_grid(
        exact.header_grid,
        skip_columns=frozenset(row_key_positions.values()),
    )
    labels: list[str] = []
    seen: set[str] = set()
    for column in range(exact.n_cols):
        if column in position_to_row_key:
            label = position_to_row_key[column]
        else:
            visible = tuple(filled[level][column] for level in range(exact.header_rows))
            if any(component == "" for component in visible):
                raise GroupedXrefError(
                    f"Dynamic column at position {column} has an incomplete visible "
                    f"label tuple {visible!r}; every level must be non-empty"
                )
            label = mapping.key_for_labels(visible)
        if label in seen:
            raise GroupedXrefError(
                f"Reconstruction produced duplicate physical column label {label!r}; "
                "matrix columns must be unique"
            )
        seen.add(label)
        labels.append(label)
    return labels


def reconstruct_grouped_matrix(
    frames: Mapping[str, Any],
    *,
    table: str,
    output: str,
    row_keys: str | Iterable[Any],
    source_frame: str,
    key_column: str,
    label_columns: Iterable[str],
    level_names: Iterable[str] | None = None,
    order_policy: Any = "source_row",
    order_columns: Iterable[Any] = (),
    drop_source: bool = False,
) -> Frames:
    """Reconstruct a :class:`GroupedMatrix` from a parsed exact table.

    Reads ``frames[table]`` (an :class:`ExactTable`), identifies the configured
    row-key columns by their leaf label, normalises merge-repeat blanks, resolves
    one live axis mapping, maps each dynamic column's visible tuple back to its
    canonical key, and builds a validated ``GroupedMatrix`` under ``output``
    through the accepted GX-2 factory. Publication is atomic.
    """
    _require_frames(frames)
    _require_name(table, field_name="table")
    _require_name(output, field_name="output")
    if drop_source and table == output:
        raise GroupedXrefError("drop_source requires a distinct output frame")
    owned_row_keys = _owned_row_keys(row_keys)
    if table not in frames:
        raise GroupedXrefError(f"Grouped reconstruction input frame {table!r} was not found")
    exact = _require_exact_table(frames[table], table=table)

    intent = _build_intent(
        source_frame=source_frame,
        key_column=key_column,
        label_columns=label_columns,
        order_policy=order_policy,
        order_columns=order_columns,
    )
    _validated_geometry(exact, depth=len(intent.label_columns))
    row_key_positions = _row_key_positions(exact, row_keys=owned_row_keys)
    _require_blank_row_key_uppers(exact, row_key_positions=row_key_positions)

    # Exactly one live mapping resolution feeds key_for_labels, build_grouped_header,
    # and the factory revalidation.
    mapping = resolve_axis_mapping(frames, intent)
    canonical_labels = _canonical_labels(
        exact,
        row_key_positions=row_key_positions,
        mapping=mapping,
    )
    flat = pd.DataFrame(
        [list(record) for record in exact.data],
        columns=pd.Index(canonical_labels),
    )
    header = build_grouped_header(
        flat,
        row_keys=owned_row_keys,
        mapping=mapping,
        level_names=level_names,
    )
    grouped = grouped_matrix_from_canonical(flat, header, mapping=mapping)

    out: dict[str, Any] = dict(frames)
    if drop_source:
        out.pop(table, None)
    out[output] = grouped
    return out


__all__ = ["reconstruct_grouped_matrix"]
