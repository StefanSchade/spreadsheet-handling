import io
import textwrap
import yaml
import pandas as pd
from spreadsheet_handling.pipeline.pipeline import build_steps_from_config, run_pipeline

def make_frames():
    A = pd.DataFrame({"id": ["1", "2"], "name": ["Alpha", "Beta"]})
    B = pd.DataFrame({"id_(A)": ["2", "1", "2"]})
    return {"A": A, "B": B}

def test_pipeline_from_yaml_fragment():
    # Simulate loading YAML without touching disk
    yaml_txt = textwrap.dedent("""
    pipeline:
      - step: validate
        mode_duplicate_ids: warn
        mode_missing_fk: warn
        defaults:
          id_field: id
          label_field: name
          detect_fk: true
          helper_prefix: "_"
      - step: apply_fks
        defaults:
          id_field: id
          label_field: name
          detect_fk: true
      - step: drop_helpers
        prefix: "_"
    """).strip()

    cfg = yaml.safe_load(io.StringIO(yaml_txt))
    steps = build_steps_from_config(cfg["pipeline"])

    frames = make_frames()
    out = run_pipeline(frames, steps)

    # Sanity checks
    assert set(out) == {"A", "B"}
    assert "id_(A)" in out["B"].columns
    assert all(not str(c).startswith("_") for c in out["B"].columns)
    # A unchanged
    pd.testing.assert_frame_equal(out["A"], frames["A"])
