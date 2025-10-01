import pandas as pd

from spreadsheet_handling.pipeline.pipeline import (
    run_pipeline,
    make_validate_step,
    make_apply_fks_step,
    make_drop_helpers_step,
    build_steps_from_config,
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

    steps = [
        make_validate_step(defaults=defaults, mode_duplicate_ids="warn", mode_missing_fk="warn"),
        make_apply_fks_step(defaults=defaults),               # should add helper column to B
        make_drop_helpers_step(prefix=defaults["helper_prefix"]),  # should drop helper columns again
    ]

    out = run_pipeline(frames, steps)

    # Structure still there
    assert set(out.keys()) == {"A", "B"}

    # A unchanged
    pd.testing.assert_frame_equal(out["A"], frames["A"])

    # B should have no helper columns after drop
    assert all(not str(c).startswith("_") for c in out["B"].columns)

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
        {"step": "apply_fks", "defaults": {"id_field": "id", "label_field": "name", "detect_fk": True}},
        {"step": "drop_helpers", "prefix": "_"},
    ]

    steps = build_steps_from_config(cfg_pipeline)
    out = run_pipeline(frames, steps)

    # basic sanity
    assert "A" in out and "B" in out
    assert "id_(A)" in out["B"].columns
    # helpers should be dropped at the end
    assert all(not str(c).startswith("_") for c in out["B"].columns)
