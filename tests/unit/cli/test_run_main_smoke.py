import types
import spreadsheet_handling.cli.apps.run as runmod

def _fake_loader_factory(kind):
    def _load(_path):
        return types.SimpleNamespace(sheets={"Kunden": []}, meta={})
    return _load

def _fake_saver(frames, out_path):
    assert hasattr(frames, "sheets")

def test_main_with_steps_only(monkeypatch):
    monkeypatch.setattr(runmod, "get_loader", _fake_loader_factory)
    monkeypatch.setattr(runmod, "get_saver", lambda kind: _fake_saver)

    # prevent file IO for --steps inline-io sniffing
    monkeypatch.setattr(runmod, "_maybe_load_inline_config_from_steps_yaml", lambda p: {})

    monkeypatch.setattr(runmod, "build_steps_from_yaml", lambda p: ["S:yaml"])
    monkeypatch.setattr(runmod, "run_pipeline", lambda frames, steps: frames)

    rc = runmod.main([
        "--steps", "steps.yml",
        "--in-kind", "json_dir", "--in-path", "in",
        "--out-kind", "json_dir", "--out-path", "out",
    ])
    assert rc == 0
