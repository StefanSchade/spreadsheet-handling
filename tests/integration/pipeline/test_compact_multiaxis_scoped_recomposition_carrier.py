"""Scoped recomposition through the pipeline binder and a persistence carrier.

FTR-COMPACT-MULTIAXIS-SCOPED-RECOMPOSITION-P4A acceptance criteria 6 and 7:
the corrected behavior must be exposed through the generic pipeline binder and
roundtrip through at least one carrier, with a realistic partial-projection
consumer scenario that preserves out-of-scope canonical rows.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.io_backends.json_backend import read_json_dir, write_json_dir
from spreadsheet_handling.pipeline.build import build_steps_from_config


pytestmark = pytest.mark.ftr("FTR-COMPACT-MULTIAXIS-SCOPED-RECOMPOSITION-P4A")


def _assert_no_internal_temp_reference(value: Any) -> None:
    if isinstance(value, str):
        assert "__compact_multiaxis_" not in value
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_no_internal_temp_reference(key)
            _assert_no_internal_temp_reference(child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            _assert_no_internal_temp_reference(child)


def test_binder_scoped_recomposition_preserves_out_of_scope_rows_through_json(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    write_json_dir(
        {
            # Editor exposes only the P-001 axis and rewrites it to Z.
            "story_matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["Z"]}),
            # The full canonical relation, code-shaped, covers P-001..P-003.
            "story_base": pd.DataFrame(
                [
                    {"feature_id": "f1", "column_key": "P-001", "code": "E"},
                    {"feature_id": "f1", "column_key": "P-002", "code": "K"},
                    {"feature_id": "f1", "column_key": "P-003", "code": "S"},
                ]
            ),
        },
        source,
    )

    result = orchestrate(
        input={"kind": "json_dir", "path": str(source)},
        output={"kind": "json_dir", "path": str(output)},
        steps=build_steps_from_config(
            [
                {
                    "step": "expand_compact_multiaxis",
                    "matrix": "story_matrix",
                    "output": "story_codes",
                    "row_keys": ["feature_id"],
                    "value_columns": ["P-001"],
                    "base_canonical_relation": "story_base",
                    "name": "story",
                },
            ]
        ),
    )

    expected = [
        {"feature_id": "f1", "column_key": "P-001", "code": "Z"},
        {"feature_id": "f1", "column_key": "P-002", "code": "K"},
        {"feature_id": "f1", "column_key": "P-003", "code": "S"},
    ]
    assert result["story_codes"].to_dict(orient="records") == expected

    # Carrier roundtrip: the preserved out-of-scope rows survive persistence.
    reloaded = read_json_dir(str(output))
    assert reloaded["story_codes"].to_dict(orient="records") == expected

    meta = yaml.safe_load((output / "_meta.yaml").read_text(encoding="utf-8"))
    assert "xref_crosstable" not in meta
    # The generic binder reserves YAML ``name`` as the BoundStep label and does
    # not forward it to the callable (CONC-PIPELINE-YAML-CALLABLE-CONTRACT), so
    # the diagnostics ``config_id`` deterministically defaults to ``output``.
    trace = meta["compact_multiaxis"]["story_codes"]
    assert trace["operation"] == "expand_compact_multiaxis"
    assert trace["base_canonical_relation"] == "story_base"
    _assert_no_internal_temp_reference(meta)
