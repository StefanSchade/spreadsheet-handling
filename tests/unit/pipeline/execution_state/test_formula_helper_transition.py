"""Standalone FormulaSpec introduction (FTR section 9; test matrix item A)."""
from __future__ import annotations

import pytest

from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    FormulaHelperCertificate,
    LookupFormulaSpecRole,
    TransitionEffect,
    Uncertified,
    classify_formula_helper_step,
    formula_helper_roles,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _step(**overrides: object):
    config = {
        "source": "matrix_raw",
        "lookup": "variables",
        "output": "matrix",
        "key": "variable_id",
        "helpers": {"fields": ["label_de"]},
        "missing": "empty",
        "helper_value_mode": "formula",
    }
    config.update(overrides)
    return build_steps_from_config([{"step": "add_lookup_helpers", **config}])[0]


def test_exact_supported_configuration_produces_the_expected_descriptor() -> None:
    certificate = classify_formula_helper_step(_step())
    assert certificate == FormulaHelperCertificate(
        source="matrix_raw",
        lookup="variables",
        output="matrix",
        source_key_column="variable_id",
        lookup_key_column="variable_id",
        fields=("label_de",),
        missing="empty",
    )

    roles = formula_helper_roles(certificate)
    assert roles == (
        LookupFormulaSpecRole(
            frame="matrix",
            column="label_de",
            source_key_column="variable_id",
            lookup_sheet="variables",
            lookup_key_column="variable_id",
            missing="empty",
            effect=TransitionEffect.INTRODUCE,
        ),
    )


def test_multiple_source_helper_roles_get_one_descriptor_each() -> None:
    certificate = classify_formula_helper_step(
        _step(helpers={"fields": ["label_de", "data_type"]})
    )
    assert isinstance(certificate, FormulaHelperCertificate)
    roles = formula_helper_roles(certificate)
    assert [role.column for role in roles] == ["label_de", "data_type"]
    assert all(role.frame == "matrix" for role in roles)
    assert all(role.effect is TransitionEffect.INTRODUCE for role in roles)


def test_asymmetric_join_key_configuration_is_certified() -> None:
    certificate = classify_formula_helper_step(
        _step(key=None, source_key="story_id", lookup_key="id")
    )
    assert isinstance(certificate, FormulaHelperCertificate)
    assert certificate.source_key_column == "story_id"
    assert certificate.lookup_key_column == "id"


def test_mixed_symmetric_and_asymmetric_keys_are_uncertified() -> None:
    certificate = classify_formula_helper_step(
        _step(key="variable_id", source_key="story_id", lookup_key="id")
    )
    assert certificate == Uncertified(reason="uncovered_configuration", detail="join_key")


def test_missing_fail_mode_is_uncertified_for_formula_role() -> None:
    # enrich_lookup itself rejects missing="fail" in formula mode, but E4's
    # classifier is independently closed: it only certifies the maintained
    # missing="empty" shape.
    certificate = classify_formula_helper_step(_step(missing="fail"))
    assert certificate == Uncertified(reason="uncovered_configuration", detail="missing")
