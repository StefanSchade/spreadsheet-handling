"""E4 falsification target (FTR section 18): mutation-after-bind safety.

Final root correction (independent E4 implementation review `01c2e93`,
section 17.3, CRITICAL falsification): an earlier correction pass made
``BoundStep.config`` a read-only ``MappingProxyType`` view, but the
``BoundFramesTargetCall`` object itself -- the actual authenticity/execution
seam -- was an ordinary mutable object with reassignable ``target``/``kwargs``
attributes, and its ``kwargs`` mapping was only *shallow*-frozen (one
``MappingProxyType`` at the top level), so a nested value (a ``list`` inside
a dict) was still the *same object* a caller's own held alias could mutate.
Both were real TOCTOU vectors: reassigning ``call.target``/``call.kwargs``
outright, or mutating a still-shared nested container through either the
caller's original alias or the exposed config/kwargs view, changed what an
already-certified call executed while its already-issued certificate stayed
unchanged.

``pipeline.types.BoundFramesTargetCall`` is now a frozen, slotted dataclass
(``call.target = x`` / ``call.kwargs = y`` both raise ``FrozenInstanceError``)
whose ``kwargs`` is *deep*-frozen at construction
(``_freeze_effective_value``): every nested ``dict``/``list``/``tuple`` is
rebuilt into new, disconnected ``MappingProxyType``/``tuple`` structures, so
the stored snapshot shares no mutable object with anything the caller still
holds. ``__call__`` thaws that snapshot into fresh, invocation-local
``dict``/``list`` containers before calling ``target`` (preserving ordinary
call semantics such as ``isinstance(helpers, dict)``), without ever mutating
the stored snapshot itself.

These tests prove: neither the executable target nor any role-relevant
configuration value can change after a certificate has been issued for a
given bound call -- not via attribute reassignment, not via the exposed
config/kwargs view, and not via a caller's original alias to a container it
originally passed in.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    FormulaHelperCertificate,
    GroupedProducerCertificate,
    classify_formula_helper_step,
    classify_grouped_producer_step,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _frames() -> dict:
    return {
        "variables": pd.DataFrame({"variable_id": ["v1"], "label_de": ["Eins"], "code": ["c1"]}),
        "matrix_raw": pd.DataFrame({"variable_id": ["v1"]}),
        "_meta": {},
    }


def _formula_step(**overrides: object):
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


def test_original_caller_held_aliases_cannot_affect_an_already_bound_call() -> None:
    """Task section 10: mutating the ORIGINAL dict/list a caller passed in,
    after binding, must not change the already-bound call's semantics."""
    fields = ["label_de"]
    helpers = {"fields": fields}
    step = build_steps_from_config(
        [
            {
                "step": "add_lookup_helpers",
                "source": "matrix_raw",
                "lookup": "variables",
                "output": "matrix",
                "key": "variable_id",
                "helpers": helpers,
                "missing": "empty",
                "helper_value_mode": "formula",
            }
        ]
    )[0]

    certificate = classify_formula_helper_step(step)
    assert isinstance(certificate, FormulaHelperCertificate)
    assert certificate.fields == ("label_de",)

    # Mutate the caller's OWN original aliases -- the bound call never
    # shares these objects (they were read once and deep-frozen).
    fields.append("code")
    helpers["fields"] = ["other"]

    out = step(_frames())
    assert set(out["matrix"].columns) & {"label_de"} == {"label_de"}
    assert "code" not in out["matrix"].columns

    # A fresh classification of the SAME (never internally mutated) bound
    # call still agrees with the original certificate.
    refreshed = classify_formula_helper_step(step)
    assert refreshed == certificate


def test_bound_calls_nested_configuration_view_is_immutable() -> None:
    step = _formula_step()
    assert type(step.fn.kwargs) is MappingProxyType
    assert type(step.fn.kwargs["helpers"]) is MappingProxyType
    assert type(step.fn.kwargs["helpers"]["fields"]) is tuple

    with pytest.raises(TypeError):
        step.fn.kwargs["helper_value_mode"] = "values"  # type: ignore[index]
    with pytest.raises(TypeError):
        step.fn.kwargs["helpers"]["fields"] = ("tampered",)  # type: ignore[index]
    with pytest.raises(AttributeError):
        step.fn.kwargs["helpers"]["fields"].append("tampered")  # type: ignore[attr-defined]


def test_target_reassignment_after_certification_is_impossible() -> None:
    step = _formula_step()
    certificate = classify_formula_helper_step(step)
    assert isinstance(certificate, FormulaHelperCertificate)

    def _malicious(frames: dict, **_kwargs: object) -> dict:
        return {**frames, "PWNED": pd.DataFrame({"x": [1]})}

    with pytest.raises(FrozenInstanceError):
        step.fn.target = _malicious  # type: ignore[misc]

    out = step(_frames())
    assert "PWNED" not in out
    # The certificate issued before the attempted reassignment still
    # truthfully describes what just executed.
    assert classify_formula_helper_step(step) == certificate


def test_kwargs_reassignment_after_certification_is_impossible() -> None:
    step = _formula_step()
    certificate = classify_formula_helper_step(step)
    assert isinstance(certificate, FormulaHelperCertificate)

    with pytest.raises(FrozenInstanceError):
        step.fn.kwargs = MappingProxyType(  # type: ignore[misc]
            {**dict(step.fn.kwargs), "helper_value_mode": "values"}
        )

    out = step(_frames())
    assert "label_de" in out["matrix"].columns
    from spreadsheet_handling.core.formulas import LookupFormulaSpec

    assert isinstance(out["matrix"]["label_de"].iloc[0], LookupFormulaSpec)
    assert classify_formula_helper_step(step) == certificate


def test_top_level_config_reassignment_is_no_longer_possible() -> None:
    step = _formula_step()
    certificate = classify_formula_helper_step(step)
    assert isinstance(certificate, FormulaHelperCertificate)

    # The exact vector the independent review used to silently diverge
    # config from execution (an earlier counterexample) now raises
    # immediately.
    with pytest.raises(TypeError):
        step.config["helper_value_mode"] = "values"  # type: ignore[index]

    # Nothing changed: the already-returned certificate and a fresh
    # classification both still agree with reality.
    assert certificate.fields == ("label_de",)
    refreshed = classify_formula_helper_step(step)
    assert refreshed == certificate


def test_nested_sequence_configuration_is_also_deep_frozen_for_grouped_producer() -> None:
    """Task section 10: prove this is not FormulaHelper-specific, using
    `row_keys` on a grouped producer."""
    row_keys = ["variable_id"]
    step = build_steps_from_config(
        [
            {
                "step": "contract_grouped_xref",
                "relation": "source",
                "output": "grouped",
                "row_keys": row_keys,
                "source_frame": "variables",
                "key_column": "variable_id",
                "label_columns": ["group"],
                "value": "value",
            }
        ]
    )[0]
    certificate = classify_grouped_producer_step(step)
    assert isinstance(certificate, GroupedProducerCertificate)
    assert certificate.row_keys == ("variable_id",)

    row_keys.append("extra_key")

    refreshed = classify_grouped_producer_step(step)
    assert refreshed == certificate
    assert type(step.fn.kwargs["row_keys"]) is tuple
