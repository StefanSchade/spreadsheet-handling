"""E4 representation fundamentals (FTR section 22): the closed uncertified default.

Proves: default is uncertified; a known callable name, registry identity, or
class/factory/object identity alone never certifies; an unknown option or
uncovered nested-callback configuration stays uncertified; and -- the
independent E4 implementation review's Blocking F1 finding -- neither a
forged ``BoundStep`` (matching config, unrelated ``fn``) nor a post-bind
config mutation can obtain a false certificate, because certification now
requires *both* a framework-authenticated binding *and* an exact
configuration.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import LookupFormulaSpec
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    FormulaHelperCertificate,
    Uncertified,
    classify_artifact_manifest_step,
    classify_expand_grouped_step,
    classify_formula_helper_step,
    classify_grouped_producer_step,
)
from spreadsheet_handling.pipeline.types import BoundStep

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")

FORMULA_HELPER_TARGET = "spreadsheet_handling.domain.transformations.enrich_lookup:enrich_lookup"


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


def _formula_frames() -> dict:
    return {
        "matrix_raw": pd.DataFrame({"variable_id": ["v1", "v2"]}),
        "variables": pd.DataFrame({"variable_id": ["v1", "v2"], "label_de": ["Eins", "Zwei"]}),
        "_meta": {},
    }


@pytest.mark.parametrize(
    "step",
    [
        # Not built through the registry at all -- a caller-supplied /
        # prebound BoundStep with no framework-reviewed target and no
        # trusted binding.
        BoundStep(
            name="custom",
            config={"target": "some.module:some_function", "helper_value_mode": "formula"},
            fn=lambda frames: frames,
        ),
        # A dotted plugin step's config *shape* (make_plugin_step builds
        # config as {"dotted": ..., "args": ...}, no "target" key at all),
        # but hand-constructed here too -- not trusted-bound either.
        BoundStep(name="plugin", config={"dotted": "x:y", "args": {}}, fn=lambda frames: frames),
        # Matching class/object shape only: config carries a real-looking
        # target string, but it is not one of the five reviewed dotted
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
        # None of these three were built by a trusted pipeline binder
        # (`step.binding` defaults to None on the public BoundStep
        # constructor), so authenticity fails before the target is even
        # compared.
        assert result.reason == "unauthenticated_binding"


def test_forged_bound_step_with_certifiable_config_and_unrelated_fn_is_uncertified() -> None:
    """F1 counterexample A (independent E4 implementation review section 4).

    A hand-constructed ``BoundStep`` whose ``config`` is a byte-for-byte
    exact certifiable ``add_lookup_helpers`` configuration, but whose ``fn``
    does something completely unrelated, must not be certified merely
    because its config looks right.
    """

    def _unrelated_fn(frames: dict) -> dict:
        return {**frames, "PWNED": pd.DataFrame({"x": [1]})}

    forged = BoundStep(
        name="forged",
        config={
            "target": FORMULA_HELPER_TARGET,
            "source": "matrix_raw",
            "lookup": "variables",
            "output": "matrix_raw",
            "key": "variable_id",
            "helpers": {"fields": ["label_de"]},
            "missing": "empty",
            "helper_value_mode": "formula",
        },
        fn=_unrelated_fn,
    )
    result = classify_formula_helper_step(forged)
    assert result == Uncertified(reason="unauthenticated_binding")

    # Confirm the premise: fn really does execute unrelated behavior, so a
    # false certificate here would have been actively misleading.
    out = forged(_formula_frames())
    assert "PWNED" in out
    assert "label_de" not in out.get("matrix_raw", pd.DataFrame()).columns


def test_post_bind_config_mutation_cannot_upgrade_execution_to_certified() -> None:
    """F1 counterexample B (independent E4 implementation review section 4).

    A real registry-built step's ``config`` is now a read-only view, so the
    exact top-level reassignment the review reproduced
    (``step.config["helper_value_mode"] = "formula"``) can no longer happen
    at all -- it raises immediately instead of silently diverging the
    certificate from execution.
    """
    step = _formula_step(helper_value_mode="values")
    assert classify_formula_helper_step(step) == Uncertified(
        reason="uncovered_configuration", detail="helper_value_mode"
    )
    result0 = step(_formula_frames())
    assert not isinstance(result0["matrix"]["label_de"].iloc[0], LookupFormulaSpec)

    with pytest.raises(TypeError):
        step.config["helper_value_mode"] = "formula"  # type: ignore[index]

    # Still uncertified, and still executes values mode -- config and
    # execution never diverged.
    assert classify_formula_helper_step(step) == Uncertified(
        reason="uncovered_configuration", detail="helper_value_mode"
    )
    result1 = step(_formula_frames())
    assert not isinstance(result1["matrix"]["label_de"].iloc[0], LookupFormulaSpec)


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


def test_mutable_post_bind_configuration_cannot_retroactively_certify() -> None:
    step = _formula_step()
    first = classify_formula_helper_step(step)
    assert isinstance(first, FormulaHelperCertificate)

    # A caller cannot even attempt the top-level reassignment that used to
    # cause divergence -- config is a read-only view.
    with pytest.raises(TypeError):
        step.config["helper_value_mode"] = "values"  # type: ignore[index]

    # Fresh classification is unaffected (nothing changed).
    second = classify_formula_helper_step(step)
    assert second == first


def test_registry_identity_alone_does_not_certify_hand_built_grouped_step() -> None:
    step = BoundStep(
        name="contract_grouped_xref",
        config={"target": "spreadsheet_handling.domain.transformations.grouped_xref:contract_grouped_xref"},
        fn=lambda frames: frames,
    )
    # Not trusted-bound at all, regardless of config content.
    result = classify_grouped_producer_step(step)
    assert result == Uncertified(reason="unauthenticated_binding")


def test_trusted_binding_alone_without_matching_target_is_still_uncertified() -> None:
    # A genuinely trusted-bound step (make_plugin_step, a real factory in
    # pipeline/steps.py) whose config simply isn't one of the five reviewed
    # dotted-target shapes at all -- authenticity passes, target match does
    # not, and the result must still be UNCERTIFIED (unrecognized_target),
    # proving the two checks are independent layers, neither sufficient
    # alone.
    from spreadsheet_handling.pipeline.steps import make_plugin_step

    step = make_plugin_step(dotted="spreadsheet_handling.domain.meta_bootstrap:bootstrap_meta")
    result = classify_formula_helper_step(step)
    assert result == Uncertified(reason="unrecognized_target")


def test_trusted_grouped_step_with_missing_required_option_is_uncertified() -> None:
    # Genuinely trusted-bound (built through the real registry/factory), but
    # missing the required source_frame -- registered target alone is still
    # not enough.
    [step] = build_steps_from_config(
        [
            {
                "step": "contract_grouped_xref",
                "relation": "r",
                "output": "o",
                "row_keys": ["k"],
                "key_column": "key",
                "label_columns": ["grp"],
            }
        ]
    )
    result = classify_grouped_producer_step(step)
    assert isinstance(result, Uncertified)
    assert result.reason == "unsupported_configuration_value"
