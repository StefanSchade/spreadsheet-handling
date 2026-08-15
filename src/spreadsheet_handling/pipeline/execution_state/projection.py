"""Projection / sink transition representation (FTR section 14).

Represents the exact role transitions needed by the accepted current exit
chain -- GroupedMatrix workbook selection/projection and the
FormulaSpec-capable renderer adapter exit -- *without* wiring them through
the macro (`select_render_frames`, `grouped_matrix_to_exact_table`,
`compose_workbook`, and the XLSX/ODS adapters remain untouched; E5 owns
calling these functions at the right point).

Facts from FTR section 10 / Follow-up Review 005 section 5 encoded here:

* Workbook projection always terminates the outer `GroupedMatrix` role and,
  for the one admitted nested composition, relocates the FormulaSpec role
  from the grouped dynamic cells to the corresponding render cell -- the old
  grouped locations do not survive projection.
* `grouped_matrix_to_exact_table`'s output, `ExactTable`, has no "column
  name" identity at all: `data` is row-major positional tuples
  (`frame.values.tolist()`). Past that point in the projection chain, a
  physical `(row, column)` position in the data grid is the only truthful
  location coordinate -- a pre-grouping flat-column name (e.g. `"value"`)
  does not survive projection and must not be presented as a render-cell
  address (independent E4 implementation review, finding F2).
* Renaming the *referenced lookup sheet* for a nested FormulaSpec is
  unsupported (compatibility rule B): the maintained frame selector does not
  open a `GroupedMatrix` to rewrite nested FormulaSpec sheet references, so a
  rename of that sheet must be representable as an invalid transition E5 can
  reject before renderer entry, rather than surfacing as a late renderer
  failure.
* Only the maintained FormulaSpec-capable adapters (`xlsx`/`ods`, matching
  `io_backends.router`'s own kind strings) may consume a FormulaSpec role;
  every other sink kind is not authorized to terminate it.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from spreadsheet_handling.domain.transformations.grouped_xref import GroupedMatrix
from spreadsheet_handling.domain.transformations.grouped_xref.model import DynamicColumn

from .roles import GroupedMatrixFormulaRole, GroupedMatrixRole, LookupFormulaSpecRole
from .vocabulary import TransitionEffect, Uncertified

# The maintained sink `kind` strings (matching `io_backends.router.SAVERS`)
# capable of consuming a FormulaSpec role. Any other kind is not authorized.
FORMULA_CAPABLE_SINK_KINDS = frozenset({"xlsx", "ods"})


def terminate_grouped_matrix_at_projection(
    role: GroupedMatrixRole | GroupedMatrixFormulaRole,
) -> GroupedMatrixRole | GroupedMatrixFormulaRole:
    """The outer `GroupedMatrix` role after `grouped_matrix_to_exact_table` /
    `compose_workbook` consumption: CONSUME/TERMINATE, unconditionally.

    Returns the role re-stated with a ``CONSUME_TERMINATE`` effect rather
    than removing it silently, so a caller can still name what was
    terminated and where (FTR section 8: distinguish the effects, never
    collapse to a boolean).
    """
    if type(role) is GroupedMatrixRole:
        return GroupedMatrixRole(
            frame=role.frame, producer=role.producer, source=role.source,
            effect=TransitionEffect.CONSUME_TERMINATE,
        )
    return GroupedMatrixFormulaRole(
        frame=role.frame, source=role.source, effect=TransitionEffect.CONSUME_TERMINATE
    )


@dataclass(frozen=True)
class ExactTableCellLocation:
    """One physical cell position in a projected `ExactTable`'s row-major
    data grid (0-based).

    `ExactTable.data` has no column-name identity (Review 005 section 5:
    "relocates nested FormulaSpec to exact-table DATA LOCATIONS"), so
    `(row, column)` is the only truthful coordinate at this point in the
    projection chain. `compose_workbook`/`build_render_plan` then copy
    `ExactTable.data` into `TableBlock.data`/`WriteDataBlock.data` in the
    same row-major, same-physical-column order (no reordering), so this
    position maps 1:1 into those render-plan structures; the further,
    purely additive offset into an absolute sheet `(row, col)` (table `top`/
    `left`/`header_rows`) is `layout_composer`'s own geometry and is not
    reconstructed here.
    """

    row: int
    column: int


def locate_nested_formula_cells(matrix: GroupedMatrix) -> tuple[ExactTableCellLocation, ...]:
    """The exact `ExactTable` data-grid positions the nested FormulaSpec role
    occupies after `grouped_matrix_to_exact_table` projection.

    Derived from the same closed `RowKeyColumn`/`DynamicColumn` header
    dispatch `dynamic_column_labels` already uses (not a parallel
    reimplementation of grouped geometry), crossed with every physical data
    row: per the accepted nested-composition descriptor, *every* dynamic
    (non-row-key) cell of a `GroupedMatrix[LookupFormulaSpec]` carries the
    role, and `grouped_matrix_to_exact_table` preserves `matrix.frame`'s row
    order and physical column order exactly (`frame.values.tolist()`), so
    these positions are provably the real projected ones -- proven by direct
    correspondence against the real projected `ExactTable` in
    `test_projection_transition.py`.
    """
    dynamic_positions = tuple(
        column.position for column in matrix.header.columns if type(column) is DynamicColumn
    )
    n_rows = matrix.frame.shape[0]
    return tuple(
        ExactTableCellLocation(row=row, column=column)
        for row in range(n_rows)
        for column in dynamic_positions
    )


@dataclass(frozen=True)
class ProjectedFormulaLocation:
    """The nested FormulaSpec role after projection, with its exact cell
    addresses.

    Not a new `ControlledRole` kind -- a location refinement of the existing
    `LookupFormulaSpecRole`. ``role.column`` intentionally keeps the
    *pre-grouping* flat helper column name as provenance only (which lookup
    helper this role originated from, useful for diagnostics/audit); it is
    documented here as *not* a render-cell address. ``cells`` names the
    actual projected `ExactTable` data-grid positions (see
    `ExactTableCellLocation`) -- the field E5 needs to enforce adapter
    consumption.
    """

    role: LookupFormulaSpecRole
    cells: tuple[ExactTableCellLocation, ...]


def relocate_nested_formula_at_projection(
    nested: GroupedMatrixFormulaRole,
    matrix: GroupedMatrix,
    *,
    render_frame: str,
) -> ProjectedFormulaLocation:
    """The nested FormulaSpec role after projection: RELOCATE to the render cell.

    The old grouped dynamic-cell location ceases to exist once the outer
    role is consumed (FTR section 11: "The old grouped locations no longer
    exist after outer-role consumption"). ``matrix`` must be the live
    `GroupedMatrix` actually being projected -- the source of the real exact
    cell locations (see `locate_nested_formula_cells`); it is not derived
    from bound configuration alone.
    """
    source = nested.source
    role = LookupFormulaSpecRole(
        frame=render_frame,
        column=source.column,
        source_key_column=source.source_key_column,
        lookup_sheet=source.lookup_sheet,
        lookup_key_column=source.lookup_key_column,
        missing=source.missing,
        effect=TransitionEffect.RELOCATE,
    )
    return ProjectedFormulaLocation(role=role, cells=locate_nested_formula_cells(matrix))


def consume_formula_at_capable_adapter(
    location: ProjectedFormulaLocation,
    *,
    sink_kind: str,
) -> LookupFormulaSpecRole | Uncertified:
    """The FormulaSpec role after a capable adapter consumes it: CONSUME/TERMINATE.

    ``sink_kind`` must be one of the maintained FormulaSpec-capable adapter
    kinds (`FORMULA_CAPABLE_SINK_KINDS`); any other sink is not authorized
    to consume the role, and this returns `Uncertified` rather than silently
    authorizing consumption at an unsupported sink.
    """
    if sink_kind not in FORMULA_CAPABLE_SINK_KINDS:
        return Uncertified(reason="uncovered_configuration", detail="sink_kind")
    role = location.role
    return LookupFormulaSpecRole(
        frame=role.frame,
        column=role.column,
        source_key_column=role.source_key_column,
        lookup_sheet=role.lookup_sheet,
        lookup_key_column=role.lookup_key_column,
        missing=role.missing,
        effect=TransitionEffect.CONSUME_TERMINATE,
    )


def reject_referenced_lookup_sheet_rename(
    nested: GroupedMatrixFormulaRole,
    *,
    sheet_renames: Mapping[str, str],
) -> Uncertified | None:
    """Compatibility rule B: renaming the nested FormulaSpec's referenced
    lookup sheet is unsupported and must reject before renderer entry.

    ``sheet_renames`` maps an old workbook-view sheet name to its new name
    (whatever shape E5's workbook-view resolution ultimately exposes); this
    function only asks whether the nested role's ``lookup_sheet`` is one of
    the *old* names being renamed. Renaming the grouped carrier's own
    *output* sheet is unaffected and stays outside this check (FTR section
    11: "a GroupedMatrix output-sheet rename binds a separate physical
    projection name... For this nested composition, the referenced lookup
    sheet name MUST remain unchanged").
    """
    if nested.source.lookup_sheet in sheet_renames:
        return Uncertified(reason="mismatched_composition", detail="referenced_lookup_sheet_rename")
    return None


__all__ = [
    "FORMULA_CAPABLE_SINK_KINDS",
    "terminate_grouped_matrix_at_projection",
    "ExactTableCellLocation",
    "locate_nested_formula_cells",
    "ProjectedFormulaLocation",
    "relocate_nested_formula_at_projection",
    "consume_formula_at_capable_adapter",
    "reject_referenced_lookup_sheet_rename",
]
