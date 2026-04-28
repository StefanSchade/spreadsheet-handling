from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.pipeline import REGISTRY, StepRegistration, build_steps_from_config, run_pipeline


pytestmark = pytest.mark.ftr("FTR-LOOKUP-FK-CONFIGURATION-STEPS-P4")


def _frames() -> dict:
    return {
        "variables": pd.DataFrame(
            {
                "ID": ["v1", "v2"],
                "sort_key": [2, 1],
                "value_label_de": ["Eins", "Zwei"],
                "module": ["m1", "m2"],
            }
        ),
        "matrix_raw": pd.DataFrame(
            {
                "ID": ["v1", "v2"],
                "value": ["x", "y"],
            }
        ),
    }


def test_configure_lookup_helpers_registry_entry() -> None:
    entry = REGISTRY["configure_lookup_helpers"]
    assert isinstance(entry, StepRegistration)
    assert entry.target == "spreadsheet_handling.domain.helper_policies:configure_lookup_helpers"


def test_add_lookup_helpers_uses_resolved_default_policy() -> None:
    steps = build_steps_from_config(
        [
            {
                "step": "configure_lookup_helpers",
                "lookup": "variables",
                "key": "ID",
                "allowed_helpers": ["sort_key", "value_label_de", "module"],
                "default_helpers": ["value_label_de"],
                "order": {"helper_position": "before_key", "sort_by": ["sort_key"]},
            },
            {
                "step": "add_lookup_helpers",
                "source": "matrix_raw",
                "lookup": "variables",
                "output": "matrix",
                "helpers": "default",
            },
        ]
    )

    out = run_pipeline(_frames(), steps)

    policy = out["_meta"]["helper_policies"]["lookup"]["variables"]
    assert policy["default_helpers"] == ["value_label_de"]
    assert list(out["matrix"]["ID"]) == ["v2", "v1"]
    assert "value_label_de" in out["matrix"].columns
    assert "module" not in out["matrix"].columns


def test_add_lookup_helpers_rejects_inline_policy_conflict() -> None:
    steps = build_steps_from_config(
        [
            {
                "step": "configure_lookup_helpers",
                "lookup": "variables",
                "key": "ID",
                "allowed_helpers": ["value_label_de"],
                "default_helpers": ["value_label_de"],
            },
            {
                "step": "add_lookup_helpers",
                "source": "matrix_raw",
                "lookup": "variables",
                "output": "matrix",
                "on": "ID",
                "helpers": {
                    "fields": ["value_label_de"],
                    "allowed": ["value_label_de", "module"],
                },
            },
        ]
    )

    with pytest.raises(ValueError, match="conflict"):
        run_pipeline(_frames(), steps)


def test_add_lookup_helpers_enforces_policy_allowlist() -> None:
    steps = build_steps_from_config(
        [
            {
                "step": "configure_lookup_helpers",
                "lookup": "variables",
                "key": "ID",
                "allowed_helpers": ["value_label_de"],
                "default_helpers": ["value_label_de"],
            },
            {
                "step": "add_lookup_helpers",
                "source": "matrix_raw",
                "lookup": "variables",
                "output": "matrix",
                "on": "ID",
                "helpers": {"fields": ["module"]},
            },
        ]
    )

    with pytest.raises(ValueError, match="not in allowed list"):
        run_pipeline(_frames(), steps)


def test_add_lookup_helpers_uses_resolved_missing_policy() -> None:
    frames = _frames()
    frames["matrix_raw"] = pd.DataFrame({"ID": ["v1", "missing"], "value": ["x", "z"]})
    steps = build_steps_from_config(
        [
            {
                "step": "configure_lookup_helpers",
                "lookup": "variables",
                "key": "ID",
                "allowed_helpers": ["value_label_de"],
                "default_helpers": ["value_label_de"],
                "missing": "empty",
            },
            {
                "step": "add_lookup_helpers",
                "source": "matrix_raw",
                "lookup": "variables",
                "output": "matrix",
                "helpers": "default",
            },
        ]
    )

    out = run_pipeline(frames, steps)

    assert out["matrix"].loc[out["matrix"]["ID"] == "missing", "value_label_de"].iloc[0] == ""
