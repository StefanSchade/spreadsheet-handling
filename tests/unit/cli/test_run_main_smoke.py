import pytest
import types
import spreadsheet_handling.cli.apps.run as runmod

pytestmark = pytest.mark.ftr("FTR-ONE-ORCHESTRATOR")


def test_main_with_steps_only(monkeypatch):
    """sheets-run with --steps and CLI I/O overrides delegates to orchestrate()."""
    called = {}

    def _fake_orchestrate(**kwargs):
        called.update(kwargs)
        return {"Kunden": []}

    monkeypatch.setattr(runmod, "orchestrate", _fake_orchestrate)

    # prevent file IO for --steps inline-io sniffing
    monkeypatch.setattr(runmod, "_maybe_load_inline_config_from_steps_yaml", lambda p: {})
    monkeypatch.setattr(runmod, "build_steps_from_yaml", lambda p: [])

    rc = runmod.main([
        "--steps", "steps.yml",
        "--in-kind", "json_dir", "--in-path", "in",
        "--out-kind", "json_dir", "--out-path", "out",
    ])
    assert rc == 0
    assert called["input"]["kind"] == "json_dir"
    assert called["output"]["kind"] == "json_dir"
