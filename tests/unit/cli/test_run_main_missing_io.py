# tests/unit/cli/test_run_main_missing_io.py
import pytest
import spreadsheet_handling.cli.apps.run as runmod

def test_main_missing_io_raises(monkeypatch):
    # Suppress file access and make sure no 'io' block is supplied.
    monkeypatch.setattr(runmod, "_maybe_load_inline_config_from_steps_yaml", lambda p: {})
    # Stub builders defensively even though this path should not reach them.
    monkeypatch.setattr(runmod, "build_steps_from_yaml", lambda p: ["S:yaml"])

    with pytest.raises(SystemExit) as e:
        runmod.main(["--steps","steps.yml"])  # no IO overrides
    msg = "Missing I/O configuration. Provide --config/--steps with 'io', or add CLI overrides."
    assert msg in str(e.value)
