"""Standalone GroupedMatrix introduction and disjoint-role locality.

FTR section 10; test matrix items B (standalone GroupedMatrix introduction),
E (two disjoint GroupedMatrix introductions), and F (locality collision
rejection).
"""
from __future__ import annotations

import pytest

from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    GroupedMatrixRole,
    GroupedProducerCertificate,
    TransitionEffect,
    Uncertified,
    classify_grouped_producer_step,
    disjoint_grouped_introduction,
    grouped_matrix_role,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _contract_step(**overrides: object):
    config = {
        "relation": "source",
        "output": "grouped",
        "row_keys": ["variable_id"],
        "source_frame": "variables",
        "key_column": "variable_id",
        "label_columns": ["group"],
        "value": "value",
    }
    config.update(overrides)
    return build_steps_from_config([{"step": "contract_grouped_xref", **config}])[0]


def _reconstruct_step(**overrides: object):
    config = {
        "table": "parsed",
        "output": "grouped",
        "row_keys": ["variable_id"],
        "source_frame": "variables",
        "key_column": "variable_id",
        "label_columns": ["group"],
    }
    config.update(overrides)
    return build_steps_from_config([{"step": "reconstruct_grouped_matrix", **config}])[0]


def test_contract_grouped_xref_produces_the_expected_descriptor() -> None:
    certificate = classify_grouped_producer_step(_contract_step())
    assert certificate == GroupedProducerCertificate(
        producer="contract_grouped_xref",
        output="grouped",
        source="source",
        value_column="value",
        drop_source=False,
        row_keys=("variable_id",),
    )
    role = grouped_matrix_role(certificate)
    assert role == GroupedMatrixRole(
        frame="grouped", producer="contract_grouped_xref", source="source",
        effect=TransitionEffect.INTRODUCE,
    )


def test_reconstruct_grouped_matrix_produces_the_expected_descriptor() -> None:
    certificate = classify_grouped_producer_step(_reconstruct_step())
    assert certificate == GroupedProducerCertificate(
        producer="reconstruct_grouped_matrix",
        output="grouped",
        source="parsed",
        value_column=None,
        drop_source=False,
        row_keys=("variable_id",),
    )


def test_unknown_option_is_uncertified() -> None:
    certificate = classify_grouped_producer_step(_contract_step(fill_value="", extra_unreviewed=1))
    assert certificate == Uncertified(reason="unknown_option", detail="contract_grouped_xref")


def test_two_disjoint_grouped_introductions_both_remain_authorized() -> None:
    existing = grouped_matrix_role(classify_grouped_producer_step(_contract_step(output="grouped_a")))
    new_certificate = classify_grouped_producer_step(
        _contract_step(relation="other_source", output="grouped_b")
    )
    assert isinstance(new_certificate, GroupedProducerCertificate)

    result = disjoint_grouped_introduction(existing, new_certificate)
    assert result is existing


def test_footprint_collision_deliberately_rejects() -> None:
    existing = grouped_matrix_role(classify_grouped_producer_step(_contract_step(output="grouped_a")))
    # The second transition reads the *first*'s output frame as its own
    # relation -- its footprint intersects the existing role's location.
    colliding_certificate = classify_grouped_producer_step(
        _contract_step(relation="grouped_a", output="grouped_b")
    )
    assert isinstance(colliding_certificate, GroupedProducerCertificate)

    result = disjoint_grouped_introduction(existing, colliding_certificate)
    assert result == Uncertified(reason="locality_collision", detail="grouped_a")


def test_drop_source_footprint_also_collides_with_a_role_at_the_dropped_frame() -> None:
    existing = grouped_matrix_role(classify_grouped_producer_step(_reconstruct_step(output="grouped_a")))
    # A later transition that *drops* the frame currently holding `existing`
    # collides even though it never "writes" that frame's contents.
    dropping_certificate = classify_grouped_producer_step(
        _contract_step(relation="grouped_a", output="grouped_b", drop_source=True)
    )
    assert isinstance(dropping_certificate, GroupedProducerCertificate)

    result = disjoint_grouped_introduction(existing, dropping_certificate)
    assert result == Uncertified(reason="locality_collision", detail="grouped_a")
