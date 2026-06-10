from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.io_backends.json_backend import write_json_dir
from spreadsheet_handling.pipeline.types import BoundStep, Frames

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def _write_input_dir(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    frames = {
        "items": pd.DataFrame({"id": ["i1"], "name": ["Item"]}),
        "_meta": {
            "version": "1.0",
            "derived": {"sheets": {"items": {"helper_columns": []}}},
        },
    }
    write_json_dir(frames, input_dir)
    return input_dir


def _add_processed_step() -> BoundStep:
    def run(frames: Frames) -> Frames:
        out = dict(frames)
        items = out["items"].copy()
        items["processed"] = "yes"
        out["items"] = items
        runtime_meta = dict(out.get("_meta") or {})
        runtime_meta["derived"] = {"sheets": {"items": {"helper_columns": ["processed"]}}}
        out["_meta"] = runtime_meta
        return out

    return BoundStep(name="private_test_step", config={}, fn=run)


def test_orchestrate_json_dir_to_discard_executes_steps_and_writes_nothing(tmp_path: Path) -> None:
    input_dir = _write_input_dir(tmp_path)
    output_path = tmp_path / "__discard__"

    result = orchestrate(
        input={"kind": "json_dir", "path": str(input_dir)},
        output={"kind": "discard", "path": str(output_path)},
        steps=[_add_processed_step()],
    )

    assert not output_path.exists()
    assert not (tmp_path / "output").exists()
    assert result["items"]["processed"].tolist() == ["yes"]


def test_orchestrate_discard_output_still_applies_persistence_boundary(tmp_path: Path) -> None:
    input_dir = _write_input_dir(tmp_path)

    result = orchestrate(
        input={"kind": "json_dir", "path": str(input_dir)},
        output={"kind": "discard", "path": "__discard__"},
        steps=[_add_processed_step()],
    )

    assert result["_meta"]["version"] == "1.0"
    assert "derived" not in result["_meta"]
