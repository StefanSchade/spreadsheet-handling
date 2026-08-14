"""FormulaSpec -> GroupedMatrix nested composition (FTR sections 10-11).

Test matrix items C (FormulaSpec -> GroupedMatrix composition) and D
(multiple source helper roles / only the selected helper nested). Exercises
the real ``enrich_lookup`` / ``contract_grouped_xref`` chain (not a hand-built
double) so the certified configuration shape is proven against actual
maintained runtime behaviour, matching the forward endpoint independently
verified by Follow-up Review 005 section 3.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup
from spreadsheet_handling.domain.transformations.grouped_xref import contract_grouped_xref
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    FormulaGroupedComposition,
    TransitionEffect,
    Uncertified,
    classify_formula_helper_step,
    classify_grouped_producer_step,
    compose_formula_to_grouped,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")

_KEYS = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")


def _frames() -> dict[str, object]:
    raw = pd.DataFrame(
        [
            {"row_id": row_id, "column_key": key}
            for row_id in ("r1", "r2")
            for key in _KEYS
        ]
    )
    # enrich_lookup joins on `row_id` alone (one row per row_id); formula
    # mode does not consume the lookup's actual values, only its key/column
    # identity, so a single row per row_id is the correct maintained shape.
    lookup_values = pd.DataFrame(
        [{"row_id": row_id, "value": f"looked_up:{row_id}", "extra": f"extra:{row_id}"} for row_id in ("r1", "r2")]
    )
    labels = pd.DataFrame(
        {
            "key": list(_KEYS),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitätendarlehen", "Festzinsdarlehen", "Guthaben"],
        }
    )
    return {"raw": raw, "lookup_values": lookup_values, "labels": labels}


def _formula_step(**overrides: object):
    config = {
        "source": "raw",
        "lookup": "lookup_values",
        "output": "enriched",
        "key": "row_id",
        "helpers": {"fields": ["value", "extra"]},
        "missing": "empty",
        "helper_value_mode": "formula",
    }
    config.update(overrides)
    return build_steps_from_config([{"step": "add_lookup_helpers", **config}])[0]


def _grouped_step(**overrides: object):
    config = {
        "relation": "enriched",
        "output": "grouped",
        "row_keys": "row_id",
        "source_frame": "labels",
        "key_column": "key",
        "label_columns": ["grp", "leaf"],
        "column_key": "column_key",
        "value": "value",
    }
    config.update(overrides)
    return build_steps_from_config([{"step": "contract_grouped_xref", **config}])[0]


def test_forward_composition_retains_all_source_helpers_and_derives_only_selected() -> None:
    formula = classify_formula_helper_step(_formula_step())
    grouped = classify_grouped_producer_step(_grouped_step())

    composition = compose_formula_to_grouped(formula, grouped)
    assert isinstance(composition, FormulaGroupedComposition)

    retained_columns = {role.column for role in composition.retained_source}
    assert retained_columns == {"value", "extra"}
    assert all(role.frame == "enriched" for role in composition.retained_source)
    assert all(role.effect is TransitionEffect.INTRODUCE for role in composition.retained_source)
    assert all(not role.pending_cleanup for role in composition.retained_source)

    assert composition.nested.frame == "grouped"
    assert composition.nested.source.column == "value"
    assert composition.nested.effect is TransitionEffect.COPY_DERIVE

    # The runtime proof: run the actual maintained chain and confirm both the
    # selected and the unselected helper survive exactly as the composition
    # descriptor claims.
    enriched = enrich_lookup(
        _frames(),
        source="raw",
        lookup="lookup_values",
        output="enriched",
        key="row_id",
        helpers={"fields": ["value", "extra"]},
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
    from spreadsheet_handling.core.formulas import LookupFormulaSpec
    from spreadsheet_handling.domain.transformations.grouped_xref import GroupedMatrix

    assert type(result["grouped"]) is GroupedMatrix
    dynamic_cells = result["grouped"].frame.drop(columns=["row_id"]).values.flatten()
    assert all(isinstance(cell, LookupFormulaSpec) for cell in dynamic_cells)
    # The retained source relation still carries both helper roles.
    assert all(isinstance(cell, LookupFormulaSpec) for cell in result["enriched"]["value"])
    assert all(isinstance(cell, LookupFormulaSpec) for cell in result["enriched"]["extra"])


def test_drop_source_marks_retained_source_roles_pending_cleanup() -> None:
    formula = classify_formula_helper_step(_formula_step())
    grouped = classify_grouped_producer_step(_grouped_step(drop_source=True))

    composition = compose_formula_to_grouped(formula, grouped)
    assert isinstance(composition, FormulaGroupedComposition)
    assert all(role.pending_cleanup for role in composition.retained_source)
    assert all(role.effect is TransitionEffect.PENDING_CLEANUP for role in composition.retained_source)


def test_mismatched_value_column_is_uncertified() -> None:
    formula = classify_formula_helper_step(_formula_step())
    # "other" was never introduced by the formula certificate.
    grouped = classify_grouped_producer_step(_grouped_step(value="other"))

    result = compose_formula_to_grouped(formula, grouped)
    assert result == Uncertified(reason="mismatched_composition", detail="value_column")


def test_mismatched_source_frame_is_uncertified() -> None:
    formula = classify_formula_helper_step(_formula_step())
    # The grouped producer reads a different relation than the formula step
    # actually wrote.
    grouped = classify_grouped_producer_step(_grouped_step(relation="something_else"))

    result = compose_formula_to_grouped(formula, grouped)
    assert result == Uncertified(reason="mismatched_composition", detail="source_frame")


def test_reconstruct_grouped_matrix_is_not_an_admitted_composition_producer() -> None:
    formula = classify_formula_helper_step(_formula_step())
    reconstruct = classify_grouped_producer_step(
        build_steps_from_config(
            [
                {
                    "step": "reconstruct_grouped_matrix",
                    "table": "enriched",
                    "output": "grouped",
                    "row_keys": "row_id",
                    "source_frame": "labels",
                    "key_column": "key",
                    "label_columns": ["grp", "leaf"],
                }
            ]
        )[0]
    )

    result = compose_formula_to_grouped(formula, reconstruct)
    assert result == Uncertified(reason="mismatched_composition", detail="producer")
