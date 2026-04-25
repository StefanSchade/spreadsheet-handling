from __future__ import annotations

import pandas as pd

from spreadsheet_handling.pipeline.pipeline import (
    REGISTRY,
    StepRegistration,
    build_steps_from_config,
    run_pipeline,
)


def test_registry_uses_descriptor_for_migrated_builder_step() -> None:
    entry = REGISTRY["flatten_headers"]
    assert isinstance(entry, StepRegistration)
    assert entry.target == "spreadsheet_handling.domain.transformations.helpers:flatten_headers"


def test_registry_uses_descriptor_for_migrated_frames_step() -> None:
    entry = REGISTRY["bootstrap_meta"]
    assert isinstance(entry, StepRegistration)
    assert entry.target == "spreadsheet_handling.domain.meta_bootstrap:bootstrap_meta"


def test_build_steps_from_config_binds_builder_style_domain_step() -> None:
    frames = {
        "Sheet1": pd.DataFrame(
            [[1, 2]],
            columns=pd.MultiIndex.from_tuples([("A", ""), ("B", "")]),
        )
    }
    steps = build_steps_from_config(
        [{"step": "flatten_headers", "mode": "level0"}]
    )

    assert steps[0].name == "flatten_headers"
    assert steps[0].config["target"].endswith(":flatten_headers")

    out = run_pipeline(frames, steps)
    assert list(out["Sheet1"].columns) == ["A", "B"]


def test_build_steps_from_config_binds_frames_first_domain_step() -> None:
    frames = {"Sheet1": pd.DataFrame({"a": [1]})}
    steps = build_steps_from_config(
        [{"step": "bootstrap_meta", "profile_defaults": {"freeze_header": True}}]
    )

    assert steps[0].name == "bootstrap_meta"
    assert steps[0].config["target"].endswith(":bootstrap_meta")

    out = run_pipeline(frames, steps)
    assert out["_meta"]["freeze_header"] is True


def test_apply_overrides_generic_registration_binds_frames_first_step() -> None:
    frames = {"Sheet1": pd.DataFrame({"a": [1]})}

    steps = build_steps_from_config(
        [{"step": "apply_overrides", "overrides": {"defaults": {"auto_filter": True}}}]
    )
    out = run_pipeline(frames, steps)

    assert steps[0].config["target"].endswith(":load_and_apply_overrides")
    assert out["_meta"]["auto_filter"] is True


def test_xref_crosstable_steps_are_config_addressable() -> None:
    frames = {
        "matrix": pd.DataFrame({
            "feature_id": ["f1"],
            "P-001": ["E"],
            "P-002": ["S"],
        })
    }
    steps = build_steps_from_config(
        [
            {
                "step": "expand_xref",
                "matrix": "matrix",
                "output": "long",
                "row_keys": ["feature_id"],
                "value_columns": ["P-001", "P-002"],
            },
            {
                "step": "contract_xref",
                "relation": "long",
                "output": "roundtrip",
                "row_keys": ["feature_id"],
            },
        ]
    )

    assert steps[0].config["target"].endswith(":expand_xref")
    assert steps[1].config["target"].endswith(":contract_xref")

    out = run_pipeline(frames, steps)

    assert out["long"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "value": "E"},
        {"feature_id": "f1", "column_key": "P-002", "value": "S"},
    ]
    assert out["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E", "P-002": "S"},
    ]


def test_legacy_registry_entry_still_builds_and_runs() -> None:
    assert not isinstance(REGISTRY["validate"], StepRegistration)

    frames = {
        "A": pd.DataFrame({"id": ["1"], "name": ["Alpha"]}),
        "B": pd.DataFrame({"id_(A)": ["1"]}),
    }
    steps = build_steps_from_config(
        [
            {
                "step": "validate",
                "mode_duplicate_ids": "warn",
                "mode_missing_fk": "warn",
                "defaults": {
                    "id_field": "id",
                    "label_field": "name",
                    "detect_fk": True,
                    "helper_prefix": "_",
                },
            }
        ]
    )

    out = run_pipeline(frames, steps)
    assert set(out) == {"A", "B"}
