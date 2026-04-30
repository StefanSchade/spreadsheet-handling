"""Minimal pipeline roundtrip integration slice.

Runs app config loading and the pipeline runner for a JSON-to-XLSX smoke path
with spreadsheet output options.
"""

from pathlib import Path

import pytest
import yaml

from spreadsheet_handling.pipeline.config import load_app_config
from spreadsheet_handling.pipeline.runner import run_pipeline

pytestmark = pytest.mark.ftr("FTR-TEST-NAMING-AND-CONVENTIONS-P3C")


def test_run_pipeline_writes_xlsx_from_json_input(tmp_path: Path):
    # input data
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "products.json").write_text(
        '[{"id":"P1","name":"A"},{"id":"P2","name":"B"}]', encoding="utf-8"
    )

    cfg = {
        "io": {
            "inputs": {"primary": {"kind": "json", "path": str(tmp_path / "in")}},
            "output": {"kind": "xlsx", "path": str(tmp_path / "out.xlsx")},
        },
        "pipeline": {"steps": []},
        "excel": {"auto_filter": True, "header_fill_rgb": "DDDDDD", "freeze_header": False},
    }
    cfg_path = tmp_path / "sheets.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    app = load_app_config(str(cfg_path))
    _frames, _meta, _issues = run_pipeline(app, run_id="it-smoke")
    assert (tmp_path / "out.xlsx").exists()
