"""E4 falsification target (FTR section 18): mutation-after-bind safety.

``pipeline.steps.make_frames_target_step`` builds ``BoundStep.config`` as
``{"target": ..., **dict(kwargs)}`` -- a *shallow* copy. A nested mutable
value (a ``list``) inside ``kwargs`` is therefore the *same object* the
step's execution closure (which closes over ``kwargs``, not ``config``)
reads at call time, so mutating ``bound_step.config[...]`` in place after
binding really does change what the next invocation of the *same BoundStep*
executes. These tests prove the value this package returns does not silently
retain that false certification once configuration has moved on, and that an
already-returned certificate is not retroactively corrupted by a later
mutation of the ``BoundStep`` it was read from.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    FormulaHelperCertificate,
    Uncertified,
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


def test_mutating_config_after_classification_cannot_downgrade_a_returned_certificate() -> None:
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

    # Reassigning a top-level config key does not even affect the actual
    # execution closure for this binder (it captures its own `kwargs`), but
    # it must also not retroactively change the already-returned value.
    step.config["helper_value_mode"] = "values"
    assert certificate.fields == ("label_de",)

    refreshed = classify_formula_helper_step(step)
    assert isinstance(refreshed, Uncertified)
