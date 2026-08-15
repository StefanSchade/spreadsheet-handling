"""E4 representation fundamentals (FTR section 22): the closed uncertified default.

Proves: default is uncertified; a known callable name, registry identity, or
class/factory/object identity alone never certifies; an unknown option or
uncovered nested-callback configuration stays uncertified; and -- the
independent E4 implementation review's Blocking F1 finding, residual pass
(review `ad700f0`) -- neither a forged ``BoundStep`` (matching config,
unrelated ``fn``) nor a post-bind config mutation nor copying/reusing the
authenticity machinery itself (``BoundFramesTargetCall``) with an unrelated
target/subclassed ``__call__`` can obtain a false certificate. Certification
is now a structural property of what a step's ``fn`` *necessarily executes*
when called, not possession of a caller-copyable marker.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import LookupFormulaSpec
from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    FormulaHelperCertificate,
    Uncertified,
    classify_artifact_manifest_step,
    classify_expand_grouped_step,
    classify_formula_helper_step,
    classify_grouped_producer_step,
)
from spreadsheet_handling.pipeline.types import BoundFramesTargetCall, BoundStep

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
        # prebound BoundStep with no framework-reviewed target and an
        # ordinary closure fn, not a BoundFramesTargetCall.
        BoundStep(
            name="custom",
            config={"target": "some.module:some_function", "helper_value_mode": "formula"},
            fn=lambda frames: frames,
        ),
        # A dotted plugin step's config *shape* (make_plugin_step builds
        # config as {"dotted": ..., "args": ...}, no "target" key at all),
        # but hand-constructed here too -- not a BoundFramesTargetCall either.
        BoundStep(name="plugin", config={"dotted": "x:y", "args": {}}, fn=lambda frames: frames),
        # Matching class/object shape only: config carries a real-looking
        # target string, but fn is a plain closure -- module.class identity
        # of the config label is not proof of what fn does.
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
        # None of these three have fn == a BoundFramesTargetCall wrapping the
        # expected target, so authenticity fails before configuration is
        # even inspected.
        assert result.reason == "unauthenticated_binding"


def test_forged_bound_step_with_certifiable_config_and_unrelated_fn_is_uncertified() -> None:
    """F1 counterexample A (original review, still closed).

    A hand-constructed ``BoundStep`` whose ``config`` is a byte-for-byte
    exact certifiable ``add_lookup_helpers`` configuration, but whose ``fn``
    is an ordinary closure doing something completely unrelated, must not be
    certified merely because its config looks right.
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


def test_reusing_the_real_binding_class_with_an_unrelated_target_is_uncertified() -> None:
    """F1 residual counterexample (independent E4 implementation review
    `ad700f0`, section 16.1), generalized to the corrected mechanism.

    The original residual defect was importing the public
    ``_TRUSTED_BINDING`` sentinel and pairing it with an unrelated ``fn`` --
    a marker provable only by *possession*, not by what actually executes.
    That sentinel no longer exists. The structurally equivalent attempt
    against the corrected mechanism is constructing a real
    ``BoundFramesTargetCall`` -- the actual authenticity seam -- but pointed
    at an unrelated callable instead of the reviewed target. This must still
    be UNCERTIFIED: authenticity is proven by *target identity*, not by
    merely using the right wrapper class.
    """

    def _unrelated_target(frames: dict, **kwargs: object) -> dict:
        return {**frames, "PWNED": pd.DataFrame({"x": [1]})}

    call = BoundFramesTargetCall(_unrelated_target, _formula_config())
    forged = BoundStep(name="forged", config={"target": FORMULA_HELPER_TARGET}, fn=call)

    result = classify_formula_helper_step(forged)
    assert result == Uncertified(reason="unauthenticated_binding")


def test_subclassing_the_real_binding_class_to_override_call_is_uncertified() -> None:
    """Another shape of the same residual attempt: subclass
    ``BoundFramesTargetCall``, point ``target`` at the real reviewed
    callable so it "looks" legitimate, but override ``__call__`` to do
    something else. The exact-type check (``type(call) is
    BoundFramesTargetCall``, never ``isinstance``) rejects this regardless
    of what ``target`` claims to be.
    """

    class _Subclass(BoundFramesTargetCall):
        def __call__(self, frames: dict) -> dict:  # pragma: no cover - never invoked
            return {**frames, "PWNED": pd.DataFrame({"x": [1]})}

    call = _Subclass(enrich_lookup, _formula_config())
    forged = BoundStep(name="forged", config={"target": FORMULA_HELPER_TARGET}, fn=call)

    result = classify_formula_helper_step(forged)
    assert result == Uncertified(reason="unauthenticated_binding")


def test_copying_a_genuine_binding_necessarily_executes_the_reviewed_behavior() -> None:
    """F1 required invariant (task section 5): a manually constructed value
    may pass certification only if the structure it supplies *necessarily*
    executes the reviewed target with the reviewed configuration. Copying a
    real ``BoundFramesTargetCall(enrich_lookup, <real config>)`` into a
    fresh ``BoundStep`` DOES certify -- but calling it can only ever run
    ``enrich_lookup`` with that exact configuration, so the certificate is
    not false: there is no way to obtain this certificate while executing
    different behavior.
    """
    kwargs = _formula_config()
    call = BoundFramesTargetCall(enrich_lookup, kwargs)
    copied = BoundStep(name="copied", config={"target": FORMULA_HELPER_TARGET}, fn=call)

    certificate = classify_formula_helper_step(copied)
    assert isinstance(certificate, FormulaHelperCertificate)

    out = copied(_formula_frames())
    assert isinstance(out["matrix"]["label_de"].iloc[0], LookupFormulaSpec)


def test_post_bind_config_mutation_cannot_upgrade_execution_to_certified() -> None:
    """F1 counterexample B (original review, still closed).

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
    # fn is a plain closure, not a BoundFramesTargetCall -- not authenticated
    # regardless of config content.
    result = classify_grouped_producer_step(step)
    assert result == Uncertified(reason="unauthenticated_binding")


def test_frames_target_call_for_a_different_reviewed_target_stays_uncertified() -> None:
    # A genuinely trusted BoundFramesTargetCall -- built through the same
    # make_frames_target_step seam every reviewed target uses -- but
    # wrapping a *different*, non-E4-reviewed target (validate_references).
    # The wrapper type matches; target identity does not.
    [step] = build_steps_from_config([{"step": "validate_references", "rules": []}])
    result = classify_formula_helper_step(step)
    assert result == Uncertified(reason="unauthenticated_binding")


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
