from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.pipeline import (
    REGISTRY,
    StepRegistration,
    build_steps_from_config,
    run_pipeline,
)

RENAMED_PIPELINE_STEPS = {
    "apply_fks": "add_fk_helpers",
    "drop_helpers": "remove_fk_helpers",
    "check_fk_helpers": "validate_fk_helpers",
    "reorder_helpers": "reorder_fk_helpers",
    "enrich_lookup": "add_lookup_helpers",
}


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
    steps = build_steps_from_config([{"step": "flatten_headers", "mode": "level0"}])

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


@pytest.mark.ftr("FTR-PIPELINE-STEP-NAMING-P4")
def test_pipeline_registry_uses_normalized_helper_step_names() -> None:
    for old_name, new_name in RENAMED_PIPELINE_STEPS.items():
        assert old_name not in REGISTRY
        assert new_name in REGISTRY


@pytest.mark.ftr("FTR-PIPELINE-STEP-NAMING-P4")
def test_replaced_pipeline_step_names_fail_clearly() -> None:
    for old_name in RENAMED_PIPELINE_STEPS:
        with pytest.raises(KeyError, match=f"Unknown step '{old_name}'"):
            build_steps_from_config([{"step": old_name}])


def test_xref_crosstable_steps_are_config_addressable() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["E"],
                "P-002": ["S"],
            }
        )
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


@pytest.mark.ftr("FTR-SPLIT-BY-DISCRIMINATOR-P4A")
def test_discriminator_split_steps_are_config_addressable() -> None:
    frames = {
        "subject_labels": pd.DataFrame(
            [
                {"subject": "sub_1", "label": "Eingang", "sprache": "de"},
                {"subject": "sub_1", "label": "entrance", "sprache": "en"},
            ]
        )
    }
    steps = build_steps_from_config(
        [
            {
                "step": "split_by_discriminator",
                "source_frame": "subject_labels",
                "discriminator_column": "sprache",
                "target_pattern": "subject_labels_{value}",
            },
            {
                "step": "merge_by_discriminator",
                "target_frame": "subject_labels",
                "discriminator_column": "sprache",
                "source_pattern": "subject_labels_{value}",
            },
        ]
    )

    assert isinstance(REGISTRY["split_by_discriminator"], StepRegistration)
    assert isinstance(REGISTRY["merge_by_discriminator"], StepRegistration)
    assert steps[0].config["target"].endswith(":split_by_discriminator")
    assert steps[1].config["target"].endswith(":merge_by_discriminator")

    out = run_pipeline(frames, steps)

    assert out["subject_labels_de"].to_dict(orient="records") == [
        {"subject": "sub_1", "label": "Eingang"},
    ]
    assert out["subject_labels"].to_dict(orient="records") == [
        {"subject": "sub_1", "label": "Eingang", "sprache": "de"},
        {"subject": "sub_1", "label": "entrance", "sprache": "en"},
    ]


def test_cell_codec_steps_are_config_addressable() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["E-R-K"],
            }
        ),
        "_meta": {
            "legend_blocks": {
                "status_codes": {
                    "entries": [
                        {"token": "E", "label": "Editable"},
                        {"token": "E-R-K", "label": "Composite whole code"},
                    ],
                }
            }
        },
    }
    steps = build_steps_from_config(
        [
            {
                "step": "expand_xref",
                "matrix": "matrix",
                "output": "long",
                "row_keys": ["feature_id"],
                "value_columns": ["P-001"],
            },
            {
                "step": "decode_cell_values",
                "source": "long",
                "output": "decoded",
                "passthrough_columns": ["feature_id", "column_key"],
                "allowed_from_legend": "status_codes",
            },
            {
                "step": "encode_cell_values",
                "source": "decoded",
                "output": "encoded",
                "group_by": ["feature_id", "column_key"],
                "allowed_from_legend": "status_codes",
            },
            {
                "step": "contract_xref",
                "relation": "encoded",
                "output": "roundtrip",
                "row_keys": ["feature_id"],
                "column_keys": ["P-001"],
            },
        ]
    )

    assert steps[1].config["target"].endswith(":decode_cell_values")
    assert steps[2].config["target"].endswith(":encode_cell_values")

    out = run_pipeline(frames, steps)

    assert out["decoded"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E-R-K"},
    ]
    assert out["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E-R-K"},
    ]


def test_compact_multiaxis_steps_are_config_addressable() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["K-E"],
            }
        )
    }
    steps = build_steps_from_config(
        [
            {
                "step": "expand_compact_multiaxis",
                "matrix": "matrix",
                "output": "explicit",
                "row_keys": ["feature_id"],
                "value_columns": ["P-001"],
                "mode": "split_tokens",
                "delimiter": "-",
                "allowed_tokens": ["E", "K"],
            },
            {
                "step": "contract_compact_multiaxis",
                "relation": "explicit",
                "output": "roundtrip",
                "row_keys": ["feature_id"],
                "mode": "split_tokens",
                "delimiter": "-",
                "allowed_tokens": ["E", "K"],
                "canonical_order": ["E", "K"],
            },
        ]
    )

    assert steps[0].config["target"].endswith(":expand_compact_multiaxis")
    assert steps[1].config["target"].endswith(":contract_compact_multiaxis")

    out = run_pipeline(frames, steps)

    assert out["explicit"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "K"},
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
    ]
    assert out["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E-K"},
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
