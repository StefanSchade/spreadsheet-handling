from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.pipeline import (
    REGISTRY,
    StepRegistration,
    build_steps_from_config,
    run_pipeline,
)


pytestmark = pytest.mark.ftr("FTR-EXPLICIT-HELPER-LOOKUP-POLICY-P4")


def test_enrich_lookup_registry_entry() -> None:
    entry = REGISTRY["enrich_lookup"]
    assert isinstance(entry, StepRegistration)
    assert entry.target == "spreadsheet_handling.domain.transformations.enrich_lookup:enrich_lookup"


def test_enrich_lookup_pipeline_smoke() -> None:
    frames = {
        "variables": pd.DataFrame({
            "ID": ["v1", "v2"],
            "sort_key": [2, 1],
            "label": ["Eins", "Zwei"],
        }),
        "matrix_raw": pd.DataFrame({
            "ID": ["v1", "v2"],
            "col_a": ["x", "y"],
        }),
    }

    steps = build_steps_from_config([{
        "step": "enrich_lookup",
        "source": "matrix_raw",
        "lookup": "variables",
        "output": "matrix",
        "on": "ID",
        "helpers": {"fields": ["sort_key", "label"]},
        "order": {"sort_by": ["sort_key"]},
    }])

    assert len(steps) == 1
    assert steps[0].name == "enrich_lookup"

    out = run_pipeline(frames, steps)
    result = out["matrix"]
    assert "sort_key" in result.columns
    assert "label" in result.columns
    assert list(result["ID"]) == ["v2", "v1"]
