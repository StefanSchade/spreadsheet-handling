from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.ftr("FTR-ONE-ORCHESTRATOR")

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.pipeline.pipeline import BoundStep, Frames


def _identity_step(name: str = "identity") -> BoundStep:
    def run(fr: Frames) -> Frames:
        # trivial no-op to exercise the pipeline
        return fr
    return BoundStep(name=name, config={}, fn=run)


def test_orchestrate_json_to_json(tmp_path: Path) -> None:
    # prepare input json_dir
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir(parents=True)

    pd.DataFrame(
        [{"id": "a", "name": "Alpha"}, {"id": "b", "name": "Bravo"}]
    ).to_json(in_dir / "products.json", orient="records", force_ascii=False, indent=2)

    frames = orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
        steps=[_identity_step()],
        header_levels=1,
    )

    # engine returns frames
    assert "products" in frames
    assert list(frames["products"].columns) == ["id", "name"]
    assert len(frames["products"]) == 2

    # and it writes output
    out_file = out_dir / "products.json"
    assert out_file.exists(), "expected products.json to be written"

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 2
    assert {d["id"] for d in data} == {"a", "b"}
