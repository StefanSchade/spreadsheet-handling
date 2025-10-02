# tests/integration/test_run_minimal_roundtrip_pipeline.py
from pathlib import Path
import yaml
from spreadsheet_handling.pipeline.config import load_app_config
from spreadsheet_handling.pipeline.runner import run_pipeline

def test_run_json_to_xlsx_smoke(tmp_path: Path):
    # input data
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "products.json").write_text(
        '[{"id":"P1","name":"A"},{"id":"P2","name":"B"}]', encoding="utf-8"
    )

    cfg = {
        "io": {
            "inputs": {"primary": {"kind": "json", "path": str(tmp_path / "in")}},
            "output": {"kind": "xlsx", "path": str(tmp_path / "out.xlsx")}
        },
        "pipeline": {"steps": []},
        "excel": {"auto_filter": True, "header_fill_rgb": "DDDDDD", "freeze_header": False}
    }
    cfg_path = tmp_path / "sheets.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    app = load_app_config(str(cfg_path))
    frames, meta, issues = run_pipeline(app, run_id="it-smoke")
    assert (tmp_path / "out.xlsx").exists()
