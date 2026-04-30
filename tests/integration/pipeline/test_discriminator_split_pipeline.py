"""Split-by-discriminator pipeline integration slice.

Exercises YAML-bound pipeline configuration for splitting a canonical table
into editable per-discriminator frames and merging it back.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.pipeline.pipeline import build_steps_from_yaml, run_pipeline

pytestmark = pytest.mark.ftr("FTR-SPLIT-BY-DISCRIMINATOR-P4A")


def test_yaml_pipeline_splits_and_merges_by_discriminator(tmp_path: Path) -> None:
    source = pd.DataFrame(
        [
            {"subject": "sub_1", "label": "Eingang", "sprache": "de"},
            {"subject": "sub_1", "label": "entrance", "sprache": "en"},
            {"subject": "sub_2", "label": "Ausgang", "sprache": "de"},
        ]
    )
    frames = {"subject_labels": source}
    config_path = tmp_path / "pipeline.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "pipeline": [
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
            }
        ),
        encoding="utf-8",
    )

    out = run_pipeline(frames, build_steps_from_yaml(str(config_path)))

    assert out["subject_labels_de"].to_dict(orient="records") == [
        {"subject": "sub_1", "label": "Eingang"},
        {"subject": "sub_2", "label": "Ausgang"},
    ]
    pd.testing.assert_frame_equal(out["subject_labels"], source)
