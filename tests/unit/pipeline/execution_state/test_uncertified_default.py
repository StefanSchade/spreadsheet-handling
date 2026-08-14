"""E4 representation fundamentals (FTR section 22): the closed uncertified default.

Proves: default is uncertified; a known callable name, registry identity, or
class/factory/object identity alone never certifies; an unknown option or
uncovered nested-callback configuration stays uncertified.
"""
from __future__ import annotations

import pytest

from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    Uncertified,
    classify_artifact_manifest_step,
    classify_expand_grouped_step,
    classify_formula_helper_step,
    classify_grouped_producer_step,
)
from spreadsheet_handling.pipeline.types import BoundStep

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _formula_config(**overrides: object) -> dict:
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
    return config


def _formula_step(**overrides: object) -> BoundStep:
    return build_steps_from_config([{"step": "add_lookup_helpers", **_formula_config(**overrides)}])[0]


@pytest.mark.parametrize(
    "step",
    [
        # Not built through the registry at all -- a caller-supplied /
        # prebound BoundStep with no framework-reviewed target.
        BoundStep(
            name="custom",
            config={"target": "some.module:some_function", "helper_value_mode": "formula"},
            fn=lambda frames: frames,
        ),
        # A dotted plugin step: config has no "target" key matching any
        # reviewed dotted path at all (make_plugin_step's own config shape).
        BoundStep(name="plugin", config={"dotted": "x:y", "args": {}}, fn=lambda frames: frames),
        # Matching class/object shape only: config carries a real-looking
        # target string, but it is not one of the seven reviewed dotted
        # paths -- module.class identity is not proof.
        BoundStep(
            name="looks_registered",
            config={"target": "spreadsheet_handling.domain.transformations.enrich_lookup.operation:enrich_lookup"},
            fn=lambda frames: frames,
        ),
    ],
    ids=["custom_callable", "dotted_plugin", "submodule_qualified_target"],
)
def test_representative_uncertified_forms_are_rejected(step: BoundStep) -> None:
    for classify in (
        classify_formula_helper_step,
        classify_grouped_producer_step,
        classify_expand_grouped_step,
        classify_artifact_manifest_step,
    ):
        result = classify(step)
        assert isinstance(result, Uncertified)
        assert result.reason == "unrecognized_target"


def test_known_callable_name_alone_does_not_certify_without_exact_configuration() -> None:
    # Exact reviewed target, but helper_value_mode is the default ("values"),
    # not the reviewed "formula" configuration.
    step = _formula_step(helper_value_mode="values")
    result = classify_formula_helper_step(step)
    assert isinstance(result, Uncertified)
    assert result.reason == "uncovered_configuration"
    assert result.detail == "helper_value_mode"


def test_unknown_option_breaks_certification() -> None:
    step = _formula_step(unexpected_extra_option="surprise")
    result = classify_formula_helper_step(step)
    assert result == Uncertified(reason="unknown_option", detail="add_lookup_helpers")


def test_policy_resolved_helpers_shorthand_stays_uncertified() -> None:
    # helpers="default" resolves fields from `_meta.helper_policies`, which
    # is not statically determinable from bound configuration alone (E4 must
    # not re-implement enrich_lookup's own policy resolution).
    step = _formula_step(helpers="default")
    result = classify_formula_helper_step(step)
    assert isinstance(result, Uncertified)
    assert result.reason == "uncovered_configuration"
    assert result.detail == "helpers"


def test_uncovered_nested_callback_shaped_option_stays_uncertified() -> None:
    def _callback(row: object) -> object:  # pragma: no cover - never invoked
        return row

    step = _formula_step(helpers={"fields": ["label_de"], "transform": _callback})
    result = classify_formula_helper_step(step)
    assert isinstance(result, Uncertified)
    assert result.reason == "uncovered_configuration"
    assert result.detail == "helpers"


def test_mutable_post_bind_configuration_does_not_retain_false_certification() -> None:
    step = _formula_step()
    first = classify_formula_helper_step(step)
    assert not isinstance(first, Uncertified)

    # Mutate the *same* BoundStep's config after an earlier successful
    # classification -- re-classifying must reflect the new state, not a
    # cached "certified" answer.
    step.config["helper_value_mode"] = "values"
    second = classify_formula_helper_step(step)
    assert isinstance(second, Uncertified)
    assert second.reason == "uncovered_configuration"


def test_registry_identity_alone_does_not_certify_grouped_producer() -> None:
    step = BoundStep(
        name="contract_grouped_xref",
        config={"target": "spreadsheet_handling.domain.transformations.grouped_xref:contract_grouped_xref"},
        fn=lambda frames: frames,
    )
    # No relation/output/row_keys at all -- registered target alone is not enough.
    result = classify_grouped_producer_step(step)
    assert isinstance(result, Uncertified)
    assert result.reason == "unsupported_configuration_value"
