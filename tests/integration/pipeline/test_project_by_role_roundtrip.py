"""End-to-end roundtrip of `project_by_role` via the YAML surface.

Mirrors the worldbuilding outbound -> inbound flow on a minimal fixture:
runs `project_by_role(outbound)` and then `project_by_role(inbound)`
through the step registry / build path, and asserts that retained
data values are preserved across the roundtrip.

See FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5 *Tests and validation*.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution import run_pipeline


pytestmark = pytest.mark.ftr("FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5")


def _matrix_view() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "story_id": ["s1", "s2"],
            "Alpha": ["E", ""],
            "title": ["Alpha story", "Beta story"],
            "Beta": ["", "S"],
        }
    )


def test_yaml_surface_roundtrip_preserves_retained_data_values() -> None:
    frames: dict[str, object] = {"story_group_matrix_view": _matrix_view()}

    outbound_steps = build_steps_from_config(
        [
            {
                "step": "project_by_role",
                "frame": "story_group_matrix_view",
                "direction": "outbound",
                "helper_columns": ["title"],
                "key_columns": ["story_id"],
            }
        ]
    )
    rendered = run_pipeline(frames, outbound_steps)

    inbound_steps = build_steps_from_config(
        [
            {
                "step": "project_by_role",
                "frame": "story_group_matrix_view",
                "direction": "inbound",
                "helper_columns": ["title"],
                "key_columns": ["story_id"],
            }
        ]
    )
    reimported = run_pipeline(rendered, inbound_steps)

    rendered_df = rendered["story_group_matrix_view"]
    assert list(rendered_df.columns) == ["title", "story_id", "Alpha", "Beta"]

    reimported_df = reimported["story_group_matrix_view"]
    assert list(reimported_df.columns) == ["story_id", "Alpha", "Beta"]
    assert reimported_df["story_id"].tolist() == ["s1", "s2"]
    assert reimported_df["Alpha"].tolist() == ["E", ""]
    assert reimported_df["Beta"].tolist() == ["", "S"]


def test_yaml_surface_rejects_invalid_direction() -> None:
    frames: dict[str, object] = {"matrix_view": _matrix_view()}
    steps = build_steps_from_config(
        [
            {
                "step": "project_by_role",
                "frame": "matrix_view",
                "direction": "sideways",
                "helper_columns": ["title"],
                "key_columns": ["story_id"],
            }
        ]
    )

    with pytest.raises(ValueError, match="outbound"):
        run_pipeline(frames, steps)
