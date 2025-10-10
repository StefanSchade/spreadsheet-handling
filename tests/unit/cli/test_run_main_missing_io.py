# tests/unit/cli/test_run_main_missing_io.py
import pytest
import spreadsheet_handling.cli.apps.run as runmod

def test_main_missing_io_raises(monkeypatch):
    # Unterdrücke Dateizugriff und sorge dafür, dass kein 'io' geliefert wird.
    monkeypatch.setattr(runmod, "_maybe_load_inline_config_from_steps_yaml", lambda p: {})
    # Builders (werden nicht erreicht, aber sicherheitshalber stubben)
    monkeypatch.setattr(runmod, "build_steps_from_yaml", lambda p: ["S:yaml"])

    with pytest.raises(SystemExit) as e:
        runmod.main(["--steps","steps.yml"])  # keine IO-Overrides
    msg = "Missing I/O configuration. Provide --config/--steps with 'io', or add CLI overrides."
    assert msg in str(e.value)
