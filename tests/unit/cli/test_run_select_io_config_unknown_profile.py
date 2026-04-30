import pytest

import spreadsheet_handling.cli.apps.run as runmod

pytestmark = pytest.mark.ftr("FTR-TEST-NAMING-AND-CONVENTIONS-P3C")


def test_select_io_config_unknown_profile_raises():
    cfg = {
        "io": {
            "profiles": {
                "local": {
                    "input": {"kind": "json_dir", "path": "in"},
                    "output": {"kind": "json_dir", "path": "out"},
                }
            }
        }
    }
    with pytest.raises(SystemExit) as e:
        runmod._select_io_config(cfg, profile="nope")
    assert "Unknown profile 'nope'" in str(e.value)
