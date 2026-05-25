import pandas as pd

from spreadsheet_handling.pipeline import (
    build_steps_from_config,
    run_pipeline,
)
from spreadsheet_handling.pipeline.steps import (
    make_validate_step,
    make_apply_fks_step,
    make_drop_helpers_step,
)

# Helpers to build tiny frames
def frames_simple():
    # Sheet A: targets with id & name
    A = pd.DataFrame({"id": ["1", "2"], "name": ["Alpha", "Beta"]})
    # Sheet B: references A via id_(A)
    B = pd.DataFrame({"id_(A)": ["2", "1", "2"]})
    return {"A": A, "B": B}


def test_pipeline_validate_apply_drop_roundtrip():
    frames = frames_simple()

    defaults = {
        "id_field": "id",
        "label_field": "name",
        "detect_fk": True,
        "helper_prefix": "_",
        "levels": 3,
    }

    steps = build_steps_from_config(
        [
            {"step": "validate", "mode_duplicate_ids": "warn", "mode_missing_fk": "warn", "defaults": defaults},
            {"step": "infer_fk_relations"},
            {"step": "add_fk_helpers", "defaults": defaults},
            {"step": "remove_fk_helpers", "prefix": defaults["helper_prefix"]},
        ]
    )

    out = run_pipeline(frames, steps)

    # Structure still there (_meta may appear from helper provenance)
    assert {"A", "B"} <= set(out.keys())

    # A unchanged
    pd.testing.assert_frame_equal(out["A"], frames["A"])

    # B should have no helper columns after drop
    assert list(out["B"].columns) == ["id_(A)"]

    # FK column is untouched
    assert "id_(A)" in out["B"].columns


def test_pipeline_build_from_config_registry():
    frames = frames_simple()
    cfg_pipeline = [
        {
            "step": "validate",
            "mode_duplicate_ids": "warn",
            "mode_missing_fk": "warn",
            "defaults": {"id_field": "id", "label_field": "name", "detect_fk": True, "helper_prefix": "_"},
        },
        {"step": "infer_fk_relations"},
        {"step": "add_fk_helpers", "defaults": {"id_field": "id", "label_field": "name", "detect_fk": True}},
        {"step": "remove_fk_helpers", "prefix": "_"},
    ]

    steps = build_steps_from_config(cfg_pipeline)
    out = run_pipeline(frames, steps)

    # basic sanity
    assert "A" in out and "B" in out
    assert "id_(A)" in out["B"].columns
    # helpers should be dropped at the end
    assert list(out["B"].columns) == ["id_(A)"]


def test_pipeline_reorder_multi_helpers_next_to_fk_in_configured_order():
    frames = {
        "A": pd.DataFrame({"id": ["1", "2"], "name": ["Alpha", "Beta"], "category": ["A", "B"]}),
        "B": pd.DataFrame({"id": ["10", "20"], "value": ["x", "y"], "id_(A)": ["2", "1"]}),
    }
    defaults = {
        "id_field": "id",
        "label_field": "name",
        "detect_fk": True,
        "helper_prefix": "_",
        "levels": 3,
    }

    out = run_pipeline(
        frames,
        build_steps_from_config(
            [
                {
                    "step": "configure_fk_helpers",
                    "targets": {
                        "A": {
                            "key": "id",
                            "allowed_helpers": ["category", "name"],
                            "default_helpers": ["category", "name"],
                        }
                    },
                },
                {"step": "add_fk_helpers", "defaults": defaults},
                {"step": "reorder_fk_helpers", "helper_prefix": "_"},
            ]
        ),
    )

    lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["B"].columns]
    assert lvl0 == ["id", "value", "id_(A)", "_A_category", "_A_name"]
