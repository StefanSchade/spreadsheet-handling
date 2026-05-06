"""Sparse crosstable pipeline composition with XRef contraction/expansion."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.pipeline.registry import build_steps_from_yaml, run_pipeline


pytestmark = pytest.mark.ftr("FTR-SPARSE-CROSSTABLE-COLLAPSE-P4A")


def test_yaml_pipeline_composes_xref_and_sparse_defaults(tmp_path: Path) -> None:
    source = pd.DataFrame(
        [
            {"feature_id": "f1", "column_key": "P-001", "value": "nein"},
            {"feature_id": "f1", "column_key": "P-002", "value": "ja"},
            {"feature_id": "f2", "column_key": "P-001", "value": "nein"},
            {"feature_id": "f2", "column_key": "P-002", "value": "nein"},
        ]
    )
    frames = {"feature_product_codes": source}
    config_path = tmp_path / "pipeline.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "pipeline": [
                    {
                        "step": "contract_xref",
                        "relation": "feature_product_codes",
                        "output": "feature_product_matrix",
                        "row_keys": ["feature_id"],
                        "column_keys": ["P-001", "P-002"],
                    },
                    {
                        "step": "sparse_collapse",
                        "frame": "feature_product_matrix",
                        "default_value": "nein",
                    },
                    {
                        "step": "sparse_expand",
                        "frame": "feature_product_matrix",
                    },
                    {
                        "step": "expand_xref",
                        "matrix": "feature_product_matrix",
                        "output": "feature_product_codes_roundtrip",
                        "row_keys": ["feature_id"],
                        "value_columns": ["P-001", "P-002"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    out = run_pipeline(frames, build_steps_from_yaml(str(config_path)))

    assert out["feature_product_matrix"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "nein", "P-002": "ja"},
        {"feature_id": "f2", "P-001": "nein", "P-002": "nein"},
    ]
    pd.testing.assert_frame_equal(out["feature_product_codes_roundtrip"], source)
