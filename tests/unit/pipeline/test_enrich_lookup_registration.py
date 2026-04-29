from __future__ import annotations

from pathlib import Path
import textwrap

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.pipeline import (
    REGISTRY,
    StepRegistration,
    build_steps_from_config,
    build_steps_from_yaml,
    run_pipeline,
)


pytestmark = [
    pytest.mark.ftr("FTR-EXPLICIT-HELPER-LOOKUP-POLICY-P4"),
    pytest.mark.ftr("FTR-PIPELINE-STEP-NAMING-P4"),
]


def test_add_lookup_helpers_registry_entry() -> None:
    entry = REGISTRY["add_lookup_helpers"]
    assert isinstance(entry, StepRegistration)
    assert entry.target == "spreadsheet_handling.domain.transformations.enrich_lookup:enrich_lookup"


def test_add_lookup_helpers_pipeline_smoke() -> None:
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
        "step": "add_lookup_helpers",
        "source": "matrix_raw",
        "lookup": "variables",
        "output": "matrix",
        "key": "ID",
        "helpers": {"fields": ["sort_key", "label"]},
        "order": {"sort_by": ["sort_key"]},
    }])

    assert len(steps) == 1
    assert steps[0].name == "add_lookup_helpers"

    out = run_pipeline(frames, steps)
    result = out["matrix"]
    assert "sort_key" in result.columns
    assert "label" in result.columns
    assert list(result["ID"]) == ["v2", "v1"]


@pytest.mark.ftr("FTR-YAML-SAFE-STEP-KEYS-P4")
def test_add_lookup_helpers_yaml_accepts_unquoted_key_alias(tmp_path: Path) -> None:
    cfg_path = tmp_path / "pipeline.yaml"
    cfg_path.write_text(
        textwrap.dedent(
            """
            pipeline:
              - step: add_lookup_helpers
                source: matrix_raw
                lookup: variables
                output: matrix
                key: ID
                helpers:
                  fields: [label]
            """
        ).strip(),
        encoding="utf-8",
    )
    frames = {
        "variables": pd.DataFrame({"ID": ["v1", "v2"], "label": ["Eins", "Zwei"]}),
        "matrix_raw": pd.DataFrame({"ID": ["v2", "v1"]}),
    }

    out = run_pipeline(frames, build_steps_from_yaml(str(cfg_path)))

    assert list(out["matrix"]["label"]) == ["Zwei", "Eins"]


@pytest.mark.ftr("FTR-YAML-SAFE-STEP-KEYS-P4")
def test_add_lookup_helpers_yaml_accepts_quoted_legacy_on(tmp_path: Path) -> None:
    cfg_path = tmp_path / "pipeline.yaml"
    cfg_path.write_text(
        textwrap.dedent(
            """
            pipeline:
              - step: add_lookup_helpers
                source: matrix_raw
                lookup: variables
                output: matrix
                "on": ID
                helpers:
                  fields: [label]
            """
        ).strip(),
        encoding="utf-8",
    )
    frames = {
        "variables": pd.DataFrame({"ID": ["v1", "v2"], "label": ["Eins", "Zwei"]}),
        "matrix_raw": pd.DataFrame({"ID": ["v2", "v1"]}),
    }

    out = run_pipeline(frames, build_steps_from_yaml(str(cfg_path)))

    assert list(out["matrix"]["label"]) == ["Zwei", "Eins"]


@pytest.mark.ftr("FTR-YAML-SAFE-STEP-KEYS-P4")
def test_add_lookup_helpers_yaml_diagnoses_unquoted_legacy_on(tmp_path: Path) -> None:
    cfg_path = tmp_path / "pipeline.yaml"
    cfg_path.write_text(
        textwrap.dedent(
            """
            pipeline:
              - step: add_lookup_helpers
                source: matrix_raw
                lookup: variables
                output: matrix
                on: ID
            """
        ).strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"on:.*key.*keys"):
        build_steps_from_yaml(str(cfg_path))
