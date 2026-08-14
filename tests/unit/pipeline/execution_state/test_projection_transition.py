"""Workbook projection / sink exit representation (FTR section 14).

Test matrix items I (workbook projection / outer role termination), J
(FormulaSpec adapter exit representation), and the referenced-lookup-sheet
rename rejection (compatibility rule B).
"""
from __future__ import annotations

import pytest

from spreadsheet_handling.pipeline.execution_state import (
    GroupedMatrixFormulaRole,
    GroupedMatrixRole,
    LookupFormulaSpecRole,
    TransitionEffect,
    Uncertified,
    reject_referenced_lookup_sheet_rename,
    relocate_nested_formula_at_projection,
    terminate_grouped_matrix_at_projection,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _source_role() -> LookupFormulaSpecRole:
    return LookupFormulaSpecRole(
        frame="enriched",
        column="value",
        source_key_column="row_id",
        lookup_sheet="lookup_values",
        lookup_key_column="row_id",
        missing="empty",
        effect=TransitionEffect.INTRODUCE,
    )


def test_standalone_grouped_matrix_terminates_at_projection() -> None:
    role = GroupedMatrixRole(
        frame="grouped", producer="contract_grouped_xref", source="rel", effect=TransitionEffect.INTRODUCE
    )
    terminated = terminate_grouped_matrix_at_projection(role)
    assert terminated.effect is TransitionEffect.CONSUME_TERMINATE
    assert terminated.frame == "grouped"


def test_nested_grouped_matrix_terminates_at_projection() -> None:
    nested = GroupedMatrixFormulaRole(frame="grouped", source=_source_role(), effect=TransitionEffect.COPY_DERIVE)
    terminated = terminate_grouped_matrix_at_projection(nested)
    assert terminated.effect is TransitionEffect.CONSUME_TERMINATE
    assert terminated.frame == "grouped"


def test_nested_formula_relocates_to_the_render_cell_at_projection() -> None:
    nested = GroupedMatrixFormulaRole(frame="grouped", source=_source_role(), effect=TransitionEffect.COPY_DERIVE)
    relocated = relocate_nested_formula_at_projection(nested, render_frame="render_plan")
    assert relocated == LookupFormulaSpecRole(
        frame="render_plan",
        column="value",
        source_key_column="row_id",
        lookup_sheet="lookup_values",
        lookup_key_column="row_id",
        missing="empty",
        effect=TransitionEffect.RELOCATE,
    )


def test_referenced_lookup_sheet_rename_is_rejected() -> None:
    nested = GroupedMatrixFormulaRole(frame="grouped", source=_source_role(), effect=TransitionEffect.COPY_DERIVE)
    result = reject_referenced_lookup_sheet_rename(
        nested, sheet_renames={"lookup_values": "renamed_lookup"}
    )
    assert result == Uncertified(
        reason="mismatched_composition", detail="referenced_lookup_sheet_rename"
    )


def test_unrelated_rename_does_not_reject() -> None:
    nested = GroupedMatrixFormulaRole(frame="grouped", source=_source_role(), effect=TransitionEffect.COPY_DERIVE)
    # Renaming the grouped carrier's own *output* sheet is unaffected --
    # only the referenced lookup sheet name is checked here.
    result = reject_referenced_lookup_sheet_rename(nested, sheet_renames={"grouped": "renamed_output"})
    assert result is None
