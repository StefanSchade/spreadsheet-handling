"""Pipeline IR write-path integration smoke slice.

Runs a minimal JSON-to-XLSX pipeline through app config loading and the real
pipeline runner.
"""

import pytest
from pathlib import Path
import yaml
from spreadsheet_handling.pipeline.runner import run_pipeline
from spreadsheet_handling.pipeline import load_app_config

pytestmark = pytest.mark.ftr("FTR-IR-WRITEPATH-P1")
def test_ir_json_to_xlsx_roundtrip(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "products.json").write_text(
        '[{"id": "P1", "name": "A"}]', encoding="utf-8"
    )

    cfg = {
        "io": {
            "inputs": {"primary": {"kind": "json", "path": str(tmp_path / "in")}},
            "output": {"kind": "xlsx", "path": str(tmp_path / "out.xlsx")}
        },
        "pipeline": {"steps": []},
    }

    cfg_path = tmp_path / "sheets.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    app = load_app_config(str(cfg_path))
    frames, meta, issues = run_pipeline(app, run_id="ir-smoke")

    assert (tmp_path / "out.xlsx").exists()
    assert not issues
