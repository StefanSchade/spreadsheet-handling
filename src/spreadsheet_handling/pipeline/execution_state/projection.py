"""Projection / sink transition representation (FTR section 14).

Represents the exact role transitions needed by the accepted current exit
chain -- GroupedMatrix workbook selection/projection and the
FormulaSpec-capable renderer adapter exit -- *without* wiring them through
the macro (`select_render_frames`, `grouped_matrix_to_exact_table`,
`compose_workbook`, and the XLSX/ODS adapters remain untouched; E5 owns
calling these functions at the right point).

Two facts from FTR section 10 / Follow-up Review 005 section 5 are encoded
here:

* Workbook projection always terminates the outer `GroupedMatrix` role and,
  for the one admitted nested composition, relocates the FormulaSpec role
  from the grouped dynamic cells to the corresponding render cell -- the old
  grouped locations do not survive projection.
* Renaming the *referenced lookup sheet* for a nested FormulaSpec is
  unsupported (compatibility rule B): the maintained frame selector does not
  open a `GroupedMatrix` to rewrite nested FormulaSpec sheet references, so a
  rename of that sheet must be representable as an invalid transition E5 can
  reject before renderer entry, rather than surfacing as a late renderer
  failure.
"""
from __future__ import annotations

from collections.abc import Mapping

from .roles import GroupedMatrixFormulaRole, GroupedMatrixRole, LookupFormulaSpecRole
from .vocabulary import TransitionEffect, Uncertified


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


def relocate_nested_formula_at_projection(
    nested: GroupedMatrixFormulaRole,
    *,
    render_frame: str,
) -> LookupFormulaSpecRole:
    """The nested FormulaSpec role after projection: RELOCATE to the render cell.

    The old grouped dynamic-cell location ceases to exist once the outer
    role is consumed (FTR section 11: "The old grouped locations no longer
    exist after outer-role consumption"), so this returns only the new
    render-side location, carrying the source's full provenance forward.
    """
    source = nested.source
    return LookupFormulaSpecRole(
        frame=render_frame,
        column=source.column,
        source_key_column=source.source_key_column,
        lookup_sheet=source.lookup_sheet,
        lookup_key_column=source.lookup_key_column,
        missing=source.missing,
        effect=TransitionEffect.RELOCATE,
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
    "terminate_grouped_matrix_at_projection",
    "relocate_nested_formula_at_projection",
    "reject_referenced_lookup_sheet_rename",
]
