"""
Consumer smoke test — FTR-DEMO-FREEZE.

Verifies that the public API surface used by spreadsheet-handling-demo
(pipeline config, runner, dotted-path plugin steps) still works.
Failures here indicate a breaking interface change in the core library.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.pipeline.config import load_app_config
from spreadsheet_handling.pipeline.runner import run_pipeline

pytestmark = pytest.mark.ftr("FTR-DEMO-FREEZE")


def _write_json_input(base: Path) -> Path:
    """Create a minimal JSON data set similar to the demo repo."""
    in_dir = base / "in"
    in_dir.mkdir()
    (in_dir / "products.json").write_text(
        '[{"id": "P1", "name": "Widget"}]', encoding="utf-8"
    )
    return in_dir


def _make_config(in_dir: Path, out_path: Path, steps: list | None = None) -> dict:
    return {
        "io": {
            "inputs": {"primary": {"kind": "json", "path": str(in_dir)}},
            "output": {"kind": "json", "path": str(out_path)},
        },
        "pipeline": {"steps": steps or []},
    }


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

def test_consumer_import_surface():
    """Core public imports must resolve without error."""
    from spreadsheet_handling.pipeline.config import load_app_config  # noqa: F811
    from spreadsheet_handling.pipeline.runner import run_pipeline  # noqa: F811
    from spreadsheet_handling.pipeline.pipeline import build_steps_from_config
    from spreadsheet_handling.orchestrator import orchestrate

    assert callable(load_app_config)
    assert callable(run_pipeline)
    assert callable(build_steps_from_config)
    assert callable(orchestrate)


def test_consumer_roundtrip_json_to_json(tmp_path: Path):
    """Minimal pipeline: JSON in → no steps → JSON out."""
    in_dir = _write_json_input(tmp_path)
    out_path = tmp_path / "out"
    cfg = _make_config(in_dir, out_path)

    cfg_file = tmp_path / "sheets.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    app = load_app_config(str(cfg_file))
    frames, meta, issues = run_pipeline(app, run_id="demo-smoke")

    assert "products" in frames
    assert frames["products"].shape[0] == 1


def test_consumer_roundtrip_json_to_xlsx(tmp_path: Path):
    """Pipeline that produces XLSX — exercises the write path the demo uses."""
    in_dir = _write_json_input(tmp_path)
    out_xlsx = tmp_path / "out.xlsx"
    cfg = {
        "io": {
            "inputs": {"primary": {"kind": "json", "path": str(in_dir)}},
            "output": {"kind": "xlsx", "path": str(out_xlsx)},
        },
        "pipeline": {"steps": []},
        "excel": {
            "auto_filter": True,
            "header_fill_rgb": "DDDDDD",
            "freeze_header": False,
        },
    }
    cfg_file = tmp_path / "sheets.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    app = load_app_config(str(cfg_file))
    frames, meta, issues = run_pipeline(app, run_id="demo-smoke")

    assert out_xlsx.exists()
    assert out_xlsx.stat().st_size > 0
