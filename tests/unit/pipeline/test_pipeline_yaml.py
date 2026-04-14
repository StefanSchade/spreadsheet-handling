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
    assert list(out["B"].columns) == ["id_(A)"]
    # A unchanged
    pd.testing.assert_frame_equal(out["A"], frames["A"])


def test_pipeline_from_yaml_supports_multi_helper_config():
    yaml_txt = textwrap.dedent("""
    pipeline:
      - step: apply_fks
        defaults:
          id_field: id
          label_field: name
          detect_fk: true
          helper_prefix: "_"
          levels: 3
          helper_fields_by_fk:
            id_(A): [category, name]
      - step: reorder_helpers
        helper_prefix: "_"
    """).strip()

    cfg = yaml.safe_load(io.StringIO(yaml_txt))
    steps = build_steps_from_config(cfg["pipeline"])

    frames = {
        "A": pd.DataFrame({"id": ["1", "2"], "name": ["Alpha", "Beta"], "category": ["A", "B"]}),
        "B": pd.DataFrame({"id": ["10", "20"], "value": ["x", "y"], "id_(A)": ["2", "1"]}),
    }
    out = run_pipeline(frames, steps)

    lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["B"].columns]
    assert lvl0 == ["id", "value", "id_(A)", "_A_category", "_A_name"]
