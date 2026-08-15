"""Workbook projection / sink exit representation (FTR section 14).

Test matrix items I (workbook projection / outer role termination), J
(FormulaSpec adapter exit representation), and the referenced-lookup-sheet
rename rejection (compatibility rule B).

Also covers the independent E4 implementation review's Blocking F2 finding:
the projected FormulaSpec location must correspond to the *actual* projected
`ExactTable` cell positions -- proven here against the real
`enrich_lookup` -> `contract_grouped_xref` -> `grouped_matrix_to_exact_table`
chain with multiple dynamic columns and multiple data rows, not a hand-built
role echoing a pre-grouping column name back at itself.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import LookupFormulaSpec
from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup
from spreadsheet_handling.domain.transformations.grouped_xref import (
    contract_grouped_xref,
    grouped_matrix_to_exact_table,
)
from spreadsheet_handling.pipeline.execution_state import (
    ExactTableCellLocation,
    GroupedMatrixFormulaRole,
    GroupedMatrixRole,
    LookupFormulaSpecRole,
    ProjectedFormulaLocation,
    TransitionEffect,
    Uncertified,
    consume_formula_at_capable_adapter,
    locate_nested_formula_cells,
    reject_referenced_lookup_sheet_rename,
    relocate_nested_formula_at_projection,
    terminate_grouped_matrix_at_projection,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")

_KEYS = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")


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


def _real_grouped_matrix():
    """A real GroupedMatrix[LookupFormulaSpec] with 3 data rows x 3 dynamic
    columns, so cell-location correspondence is proven over multiple rows
    and multiple columns, not just one of each."""
    raw = pd.DataFrame(
        [{"row_id": row_id, "column_key": key} for row_id in ("r1", "r2", "r3") for key in _KEYS]
    )
    lookup_values = pd.DataFrame(
        [{"row_id": row_id, "value": f"looked_up:{row_id}"} for row_id in ("r1", "r2", "r3")]
    )
    labels = pd.DataFrame(
        {
            "key": list(_KEYS),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitätendarlehen", "Festzinsdarlehen", "Guthaben"],
        }
    )
    enriched = enrich_lookup(
        {"raw": raw, "lookup_values": lookup_values, "labels": labels},
        source="raw",
        lookup="lookup_values",
        output="enriched",
        key="row_id",
        helpers={"fields": ["value"]},
        missing="empty",
        helper_value_mode="formula",
    )
    result = contract_grouped_xref(
        enriched,
        relation="enriched",
        output="grouped",
        row_keys="row_id",
        source_frame="labels",
        key_column="key",
        label_columns=["grp", "leaf"],
        column_key="column_key",
        value="value",
    )
    return result["grouped"]


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


def test_nested_formula_relocation_names_real_projected_exact_table_cells() -> None:
    matrix = _real_grouped_matrix()
    nested = GroupedMatrixFormulaRole(frame="grouped", source=_source_role(), effect=TransitionEffect.COPY_DERIVE)

    location = relocate_nested_formula_at_projection(nested, matrix, render_frame="render_plan")
    assert isinstance(location, ProjectedFormulaLocation)

    # The role's `column` is documented provenance only (pre-grouping helper
    # column identity), not a render-cell address.
    assert location.role == LookupFormulaSpecRole(
        frame="render_plan",
        column="value",
        source_key_column="row_id",
        lookup_sheet="lookup_values",
        lookup_key_column="row_id",
        missing="empty",
        effect=TransitionEffect.RELOCATE,
    )

    # 3 rows x 3 dynamic columns (row_id is the one row-key column, excluded).
    assert len(location.cells) == 9
    assert len(set(location.cells)) == 9  # every location distinct

    # Real-projection correspondence: every declared cell is exactly where a
    # LookupFormulaSpec instance actually sits in the real projected
    # ExactTable, and every LookupFormulaSpec instance in that table is
    # declared -- proven in both directions, not just "one column label".
    exact = grouped_matrix_to_exact_table(matrix)
    formula_positions = {
        ExactTableCellLocation(row=row, column=col)
        for row, record in enumerate(exact.data)
        for col, cell in enumerate(record)
        if isinstance(cell, LookupFormulaSpec)
    }
    assert set(location.cells) == formula_positions

    # The old grouped dynamic-cell location does not survive: outer identity
    # terminates at the same projection step.
    terminated = terminate_grouped_matrix_at_projection(nested)
    assert terminated.effect is TransitionEffect.CONSUME_TERMINATE


def test_locate_nested_formula_cells_matches_real_projection_directly() -> None:
    matrix = _real_grouped_matrix()
    cells = locate_nested_formula_cells(matrix)
    exact = grouped_matrix_to_exact_table(matrix)

    for cell in cells:
        assert isinstance(exact.data[cell.row][cell.column], LookupFormulaSpec)
    # Row-key column (position 0) never appears among the declared cells.
    assert all(cell.column != 0 for cell in cells)


def test_capable_adapter_consumes_the_relocated_role() -> None:
    matrix = _real_grouped_matrix()
    nested = GroupedMatrixFormulaRole(frame="grouped", source=_source_role(), effect=TransitionEffect.COPY_DERIVE)
    location = relocate_nested_formula_at_projection(nested, matrix, render_frame="render_plan")

    for sink_kind in ("xlsx", "ods"):
        consumed = consume_formula_at_capable_adapter(location, sink_kind=sink_kind)
        assert consumed == LookupFormulaSpecRole(
            frame="render_plan",
            column="value",
            source_key_column="row_id",
            lookup_sheet="lookup_values",
            lookup_key_column="row_id",
            missing="empty",
            effect=TransitionEffect.CONSUME_TERMINATE,
        )


def test_unsupported_sink_does_not_silently_certify_formula_consumption() -> None:
    matrix = _real_grouped_matrix()
    nested = GroupedMatrixFormulaRole(frame="grouped", source=_source_role(), effect=TransitionEffect.COPY_DERIVE)
    location = relocate_nested_formula_at_projection(nested, matrix, render_frame="render_plan")

    for sink_kind in ("json", "csv", "yaml_dir", "unknown"):
        result = consume_formula_at_capable_adapter(location, sink_kind=sink_kind)
        assert result == Uncertified(reason="uncovered_configuration", detail="sink_kind")


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
