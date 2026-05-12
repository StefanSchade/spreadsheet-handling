from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.pipeline.types import BoundStep, Frames

pytestmark = pytest.mark.ftr("FTR-REVIEW-001-QUICK-WINS-P3")


def _write_json_input(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "products.json").write_text(
        json.dumps([{"id": "P1", "name": "Widget"}], ensure_ascii=False),
        encoding="utf-8",
    )


def _add_meta(frames: Frames) -> Frames:
    frames["_meta"] = {"sheets": {"products": {"freeze_header": True}}}  # type: ignore[assignment]
    return frames


@pytest.mark.parametrize(
    ("out_kind", "visible_output", "meta_output"),
    [
        ("yaml_dir", "products.yml", "_meta.yml"),
        ("xml_dir", "products.xml", "_meta.xml"),
    ],
)
def test_meta_producing_pipeline_can_write_simple_directory_outputs(
    tmp_path: Path,
    out_kind: str,
    visible_output: str,
    meta_output: str,
) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / out_kind
    _write_json_input(in_dir)

    frames = orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": out_kind, "path": str(out_dir)},
        steps=[BoundStep(name="add_meta", config={}, fn=_add_meta)],
    )

    assert isinstance(frames["products"], pd.DataFrame)
    assert frames["_meta"]["sheets"]["products"]["freeze_header"] is True
    assert (out_dir / visible_output).exists()
    assert not (out_dir / meta_output).exists()
