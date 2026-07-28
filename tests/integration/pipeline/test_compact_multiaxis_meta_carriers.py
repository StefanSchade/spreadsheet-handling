"""Compact Multiaxis diagnostics and temp suppression across persistence carriers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.io_backends.json_backend import write_json_dir
from spreadsheet_handling.pipeline.build import build_steps_from_config


pytestmark = pytest.mark.ftr("FTR-COMPACT-MULTIAXIS-META-PERSISTENCE-CORRECTION-P5")


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


def _persisted_meta(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load((path / "_meta.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_structured_persistence_omits_expand_internal_xref_entry(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    write_json_dir(
        {
            "matrix": pd.DataFrame(
                {
                    "feature_id": ["f1"],
                    "A": ["E"],
                }
            ),
        },
        source,
    )

    orchestrate(
        input={"kind": "json_dir", "path": str(source)},
        output={"kind": "json_dir", "path": str(output)},
        steps=build_steps_from_config(
            [
                {
                    "step": "expand_compact_multiaxis",
                    "matrix": "matrix",
                    "output": "explicit",
                    "row_keys": ["feature_id"],
                    "name": "compact",
                },
                {
                    "step": "configure_pipeline_cleanup",
                    "keep_frames": ["matrix", "explicit"],
                },
            ]
        ),
    )

    meta = _persisted_meta(output)
    assert "xref_crosstable" not in meta
    assert meta["compact_multiaxis"]["explicit"]["operation"] == ("expand_compact_multiaxis")
    assert "pipeline_cleanup" not in meta
    _assert_no_internal_temp_reference(meta)


def test_structured_persistence_omits_contract_internal_xref_entry(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    write_json_dir(
        {
            "explicit": pd.DataFrame(
                [
                    {
                        "feature_id": "f1",
                        "column_key": "A",
                        "code": "E",
                    },
                ]
            ),
        },
        source,
    )

    orchestrate(
        input={"kind": "json_dir", "path": str(source)},
        output={"kind": "json_dir", "path": str(output)},
        steps=build_steps_from_config(
            [
                {
                    "step": "contract_compact_multiaxis",
                    "relation": "explicit",
                    "output": "matrix",
                    "row_keys": ["feature_id"],
                    "name": "compact",
                },
            ]
        ),
    )

    meta = _persisted_meta(output)
    assert "xref_crosstable" not in meta
    assert meta["compact_multiaxis"]["explicit"]["operation"] == ("contract_compact_multiaxis")
    _assert_no_internal_temp_reference(meta)


def test_xlsx_carrier_roundtrip_preserves_trace_without_temp_reference(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    workbook = tmp_path / "compact.xlsx"
    write_json_dir(
        {
            "matrix": pd.DataFrame(
                {
                    "feature_id": ["f1"],
                    "A": ["E"],
                }
            ),
        },
        source,
    )

    orchestrate(
        input={"kind": "json_dir", "path": str(source)},
        output={"kind": "xlsx", "path": str(workbook)},
        steps=build_steps_from_config(
            [
                {
                    "step": "expand_compact_multiaxis",
                    "matrix": "matrix",
                    "output": "explicit",
                    "row_keys": ["feature_id"],
                    "name": "compact",
                },
            ]
        ),
    )
    loaded = orchestrate(
        input={"kind": "xlsx", "path": str(workbook)},
        output={"kind": "discard", "path": "-"},
    )

    meta = loaded["_meta"]
    assert "xref_crosstable" not in meta
    assert meta["compact_multiaxis"]["explicit"]["operation"] == ("expand_compact_multiaxis")
    _assert_no_internal_temp_reference(meta)
