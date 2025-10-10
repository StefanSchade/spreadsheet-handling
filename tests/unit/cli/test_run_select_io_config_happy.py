# tests/unit/cli/test_run_select_io_config_happy.py
import spreadsheet_handling.cli.apps.run as runmod

def test__select_io_config_profile_ok():
    cfg = {"io": {"profiles": {"local": {"input": {"kind":"json_dir","path":"in"},
                                         "output":{"kind":"json_dir","path":"out"}}}}}
    sel = runmod._select_io_config(cfg, profile="local")
    assert sel["input"]["kind"] == "json_dir"
