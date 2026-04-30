import pytest
import yaml

import spreadsheet_handling.cli.apps.run as runmod

pytestmark = pytest.mark.ftr("FTR-TEST-NAMING-AND-CONVENTIONS-P3C")


def test_maybe_load_inline_config_keeps_io_and_pipeline_keys(tmp_path):
    steps_path = tmp_path / "steps.yml"
    steps_path.write_text(
        yaml.safe_dump(
            {
                "io": {
                    "input": {"kind": "json_dir", "path": "in"},
                    "output": {"kind": "json_dir", "path": "out"},
                },
                "pipelines": {"clean": [{"factory": "p.mod:make", "args": {}}]},
                "pipeline": [{"factory": "p.mod:make", "args": {}}],
            }
        ),
        encoding="utf-8",
    )

    out = runmod._maybe_load_inline_config_from_steps_yaml(str(steps_path))
    assert "io" in out and "pipelines" in out and "pipeline" in out
