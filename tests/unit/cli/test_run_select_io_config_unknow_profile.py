# tests/unit/cli/test_run_select_io_config_unknown_profile.py
import pytest
import spreadsheet_handling.cli.apps.run as runmod

def test__select_io_config_unknown_profile_raises():
    cfg = {"io": {"profiles": {"local": {"input": {"kind":"json_dir","path":"in"},
                                         "output":{"kind":"json_dir","path":"out"}}}}}
    with pytest.raises(SystemExit) as e:
        runmod._select_io_config(cfg, profile="nope")
    assert "Unknown profile 'nope'" in str(e.value)
