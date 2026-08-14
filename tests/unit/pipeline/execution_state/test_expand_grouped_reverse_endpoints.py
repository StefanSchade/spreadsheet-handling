"""Reverse expand_grouped_xref endpoints for the nested FormulaSpec case.

FTR section 10, "FormulaSpec-in-GroupedMatrix composition descriptor",
reverse retain/drop endpoints. Test matrix items G (reverse grouped expand
retain) and H (reverse grouped expand drop + pending cleanup), pinned against
the actual runtime chain per Independent Follow-up Review 005 section 6.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import LookupFormulaSpec
from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup
from spreadsheet_handling.domain.transformations.grouped_xref import (
    GroupedMatrix,
    contract_grouped_xref,
    expand_grouped_xref,
)
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    ExpandDropProduct,
    ExpandRetainProduct,
    TransitionEffect,
    classify_expand_grouped_step,
    classify_formula_helper_step,
    classify_grouped_producer_step,
    compose_formula_to_grouped,
    dynamic_column_labels,
    resolve_formula_expand_transition,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")

_KEYS = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")


def _frames() -> dict[str, object]:
    raw = pd.DataFrame(
        [{"row_id": row_id, "column_key": key} for row_id in ("r1", "r2") for key in _KEYS]
    )
    lookup_values = pd.DataFrame(
        [{"row_id": row_id, "value": f"looked_up:{row_id}"} for row_id in ("r1", "r2")]
    )
    labels = pd.DataFrame(
        {
            "key": list(_KEYS),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitätendarlehen", "Festzinsdarlehen", "Guthaben"],
        }
    )
    return {"raw": raw, "lookup_values": lookup_values, "labels": labels}


def _build_nested_matrix() -> dict[str, object]:
    enriched = enrich_lookup(
        _frames(),
        source="raw",
        lookup="lookup_values",
        output="enriched",
        key="row_id",
        helpers={"fields": ["value"]},
        missing="empty",
        helper_value_mode="formula",
    )
    return contract_grouped_xref(
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


def _nested_role():
    formula_step = build_steps_from_config(
        [
            {
                "step": "add_lookup_helpers",
                "source": "raw",
                "lookup": "lookup_values",
                "output": "enriched",
                "key": "row_id",
                "helpers": {"fields": ["value"]},
                "missing": "empty",
                "helper_value_mode": "formula",
            }
        ]
    )[0]
    grouped_step = build_steps_from_config(
        [
            {
                "step": "contract_grouped_xref",
                "relation": "enriched",
                "output": "grouped",
                "row_keys": "row_id",
                "source_frame": "labels",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
                "column_key": "column_key",
                "value": "value",
            }
        ]
    )[0]
    composition = compose_formula_to_grouped(
        classify_formula_helper_step(formula_step),
        classify_grouped_producer_step(grouped_step),
    )
    return composition.nested


def test_retain_mode_produces_the_nested_output_product() -> None:
    matrix_frames = _build_nested_matrix()
    expand_step = build_steps_from_config(
        [
            {
                "step": "expand_grouped_xref",
                "matrix": "grouped",
                "output": "expanded",
                "row_keys": "row_id",
                "source_frame": "labels",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
                "column_key": "column_key",
                "value": "value",
                "drop_source": False,
            }
        ]
    )[0]
    certificate = classify_expand_grouped_step(expand_step)
    nested = _nested_role()

    product = resolve_formula_expand_transition(certificate, nested, restored_dynamic_columns=())
    assert isinstance(product, ExpandRetainProduct)
    assert product.nested is nested
    assert product.output.frame == "expanded"
    assert product.output.column == "value"
    assert product.output.effect is TransitionEffect.COPY_DERIVE

    # Runtime proof: the nested carrier remains a GroupedMatrix and the
    # expanded output frame carries derived FormulaSpec occurrences.
    result = expand_grouped_xref(
        matrix_frames,
        matrix="grouped",
        output="expanded",
        row_keys="row_id",
        source_frame="labels",
        key_column="key",
        label_columns=["grp", "leaf"],
        column_key="column_key",
        value="value",
        drop_source=False,
    )
    assert type(result["grouped"]) is GroupedMatrix
    assert all(isinstance(cell, LookupFormulaSpec) for cell in result["expanded"]["value"])


def test_drop_mode_terminates_outer_identity_and_marks_restored_source_pending_cleanup() -> None:
    matrix_frames = _build_nested_matrix()
    matrix = matrix_frames["grouped"]
    restored_columns = dynamic_column_labels(matrix)
    assert restored_columns  # sanity: the header actually describes dynamic columns

    expand_step = build_steps_from_config(
        [
            {
                "step": "expand_grouped_xref",
                "matrix": "grouped",
                "output": "expanded",
                "row_keys": "row_id",
                "source_frame": "labels",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
                "column_key": "column_key",
                "value": "value",
                "drop_source": True,
            }
        ]
    )[0]
    certificate = classify_expand_grouped_step(expand_step)
    nested = _nested_role()

    product = resolve_formula_expand_transition(
        certificate, nested, restored_dynamic_columns=restored_columns
    )
    assert isinstance(product, ExpandDropProduct)
    assert {role.column for role in product.restored_source} == set(restored_columns)
    assert all(role.frame == "grouped" for role in product.restored_source)
    assert all(role.pending_cleanup for role in product.restored_source)
    assert all(role.effect is TransitionEffect.RELOCATE for role in product.restored_source)
    assert product.terminated.effect is TransitionEffect.CONSUME_TERMINATE
    assert product.output.frame == "expanded"
    assert product.output.effect is TransitionEffect.COPY_DERIVE

    # Runtime proof, matching Review 005 section 6 exactly: the outer
    # GroupedMatrix identity ends inside expansion; `grouped` becomes a plain
    # restored flat DataFrame with FormulaSpec cells, marked pending cleanup.
    result = expand_grouped_xref(
        matrix_frames,
        matrix="grouped",
        output="expanded",
        row_keys="row_id",
        source_frame="labels",
        key_column="key",
        label_columns=["grp", "leaf"],
        column_key="column_key",
        value="value",
        drop_source=True,
    )
    assert type(result["grouped"]) is pd.DataFrame
    dynamic_cells = result["grouped"].drop(columns=["row_id"]).values.flatten()
    assert all(isinstance(cell, LookupFormulaSpec) for cell in dynamic_cells)
    assert all(isinstance(cell, LookupFormulaSpec) for cell in result["expanded"]["value"])
    drop_frames = result["_meta"]["pipeline_cleanup"]["drop_frames"]
    assert "grouped" in drop_frames
