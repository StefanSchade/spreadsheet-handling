from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import spreadsheet_handling.pipeline.config as config_module
from spreadsheet_handling.pipeline.config import load_app_config


pytestmark = pytest.mark.ftr("FTR-REVIEW-001-BACKEND-DISPATCH-P4A-SLICE02")


def _base_config() -> dict:
    return {
        "io": {
            "inputs": {"primary": {"kind": "json", "path": "in"}},
            "output": {"kind": "json", "path": "out"},
        }
    }


def _write_config(tmp_path: Path, cfg: dict) -> Path:
    path = tmp_path / "sheets.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_app_config_uses_canonical_step_pipeline_list(tmp_path: Path) -> None:
    cfg = _base_config()
    cfg["pipeline"] = [{"step": "identity"}]

    app = load_app_config(str(_write_config(tmp_path, cfg)))

    assert app.pipeline == [{"step": "identity"}]
    assert not hasattr(config_module, "StepRef")
    assert not hasattr(config_module, "PipelineConfig")


def test_app_config_loads_io_header_levels(tmp_path: Path) -> None:
    cfg = _base_config()
    cfg["io"]["inputs"]["primary"]["header_levels"] = 2

    app = load_app_config(str(_write_config(tmp_path, cfg)))

    assert app.io.inputs["primary"].header_levels == 2
    assert app.io.output.header_levels == 1


def test_app_config_rejects_legacy_pipeline_steps_dialect(tmp_path: Path) -> None:
    cfg = _base_config()
    cfg["pipeline"] = {"steps": [{"factory": "pkg.mod:make_step"}]}

    with pytest.raises(ValueError) as exc_info:
        load_app_config(str(_write_config(tmp_path, cfg)))

    message = str(exc_info.value)
    assert "canonical step: dialect" in message
    assert "Example: pipeline: - step: identity" in message
