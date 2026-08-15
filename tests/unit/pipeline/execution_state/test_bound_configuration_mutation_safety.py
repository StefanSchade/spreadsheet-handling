"""E4 falsification target (FTR section 18): mutation-after-bind safety.

``pipeline.steps.make_frames_target_step`` builds ``BoundStep.config`` as a
read-only ``MappingProxyType`` view over ``{"target": ..., **dict(kwargs)}``
-- a *shallow* copy. A nested mutable value (a ``list``) inside that dict is
therefore the *same object* the step's execution closure (which closes over
the original ``kwargs``, not the ``config`` view) reads at call time, so
mutating a *nested* value reachable through ``bound_step.config[...]`` in
place after binding really does change what the next invocation of the same
``BoundStep`` executes -- a real, consistently-observed change, not a
divergence, because both ``config`` and the closure see the identical
object. A *top-level* key reassignment on ``config``, which used to cause a
genuine, silent config/execution divergence (the independent E4
implementation review's Blocking F1 finding, counterexample B), now raises
immediately instead: ``config`` is frozen at bind time.

These tests prove: the value this package returns does not silently retain
a stale certification once configuration has genuinely moved on (nested
mutation); an already-returned certificate is not retroactively corrupted by
a later mutation of the ``BoundStep`` it was read from; and top-level
reassignment -- the vector that used to produce false certification -- is no
longer possible at all.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    FormulaHelperCertificate,
    classify_formula_helper_step,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _frames() -> dict:
    return {
        "variables": pd.DataFrame({"variable_id": ["v1"], "label_de": ["Eins"], "code": ["c1"]}),
        "matrix_raw": pd.DataFrame({"variable_id": ["v1"]}),
        "_meta": {},
    }


def test_mutating_the_shared_helpers_list_after_bind_changes_what_actually_runs() -> None:
    """Demonstrates the real hazard: config and the execution closure share
    the same nested list object, so an in-place mutation is not cosmetic."""
    fields = ["label_de"]
    step = build_steps_from_config(
        [
            {
                "step": "add_lookup_helpers",
                "source": "matrix_raw",
                "lookup": "variables",
                "output": "matrix",
                "key": "variable_id",
                "helpers": {"fields": fields},
                "missing": "empty",
                "helper_value_mode": "formula",
            }
        ]
    )[0]

    certificate = classify_formula_helper_step(step)
    assert isinstance(certificate, FormulaHelperCertificate)
    assert certificate.fields == ("label_de",)

    # Mutate the list *in place* after classification -- this is the same
    # object the bound closure will read on the next call.
    step.config["helpers"]["fields"].append("code")

    out = step(_frames())
    assert set(out["matrix"].columns) & {"label_de", "code"} == {"label_de", "code"}

    # The already-returned certificate is an immutable snapshot: it must not
    # have silently grown a "code" field just because the live config did.
    assert certificate.fields == ("label_de",)

    # A *fresh* classification of the same (now-mutated) step honestly
    # reflects the current configuration.
    refreshed = classify_formula_helper_step(step)
    assert isinstance(refreshed, FormulaHelperCertificate)
    assert refreshed.fields == ("label_de", "code")


def test_top_level_config_reassignment_is_no_longer_possible() -> None:
    step = build_steps_from_config(
        [
            {
                "step": "add_lookup_helpers",
                "source": "matrix_raw",
                "lookup": "variables",
                "output": "matrix",
                "key": "variable_id",
                "helpers": {"fields": ["label_de"]},
                "missing": "empty",
                "helper_value_mode": "formula",
            }
        ]
    )[0]

    certificate = classify_formula_helper_step(step)
    assert isinstance(certificate, FormulaHelperCertificate)

    # The exact vector the independent review used to silently diverge
    # config from execution (counterexample B) now raises immediately.
    with pytest.raises(TypeError):
        step.config["helper_value_mode"] = "values"  # type: ignore[index]

    # Nothing changed: the already-returned certificate and a fresh
    # classification both still agree with reality.
    assert certificate.fields == ("label_de",)
    refreshed = classify_formula_helper_step(step)
    assert refreshed == certificate
