import types
import spreadsheet_handling.cli.apps.run as runmod

def _fake_loader_factory(kind):
    # Return a loader that ignores the path and yields a minimal frames object
    def _load(_path):
        return types.SimpleNamespace(sheets={"Kunden": []}, meta={})
    return _load

def _fake_saver(frames, out_path):
    # no-op, just prove we got here
    assert hasattr(frames, "sheets")
    assert isinstance(out_path, str)

def test_main_with_real_steps_file(tmp_path, monkeypatch):
    steps_path = tmp_path / "steps.yml"
    steps_path.write_text("pipeline:\n  - factory: p.mod:make\n    args: {}\n")

    monkeypatch.setattr(runmod, "get_loader", _fake_loader_factory)
    monkeypatch.setattr(runmod, "get_saver", lambda kind: _fake_saver)
    monkeypatch.setattr(runmod, "build_steps_from_yaml", lambda p: ["S:yaml"])
    monkeypatch.setattr(runmod, "run_pipeline", lambda frames, steps: frames)

    rc = runmod.main([
        "--steps", str(steps_path),
        "--in-kind", "json_dir", "--in-path", "in",
        "--out-kind", "json_dir", "--out-path", "out",
    ])
    assert rc == 0

def test_main_with_top_level_pipeline(tmp_path, monkeypatch):
    # --- write a real file so open() doesn't fail ---
    cfg_path = tmp_path / "dummy.yml"
    cfg_path.write_text("irrelevant: true\n")

    # --- fake parsed YAML payload returned by yaml.safe_load ---
    fake_cfg = {
        "io": {
            "input": {"kind": "json_dir", "path": "in"},
            "output": {"kind": "json_dir", "path": "out"},
        },
        "pipeline": [{"factory": "p.mod:make", "args": {}}],
    }
    monkeypatch.setattr(runmod.yaml, "safe_load", lambda f: fake_cfg)

    # --- keep runtime pure & quick ---
    monkeypatch.setattr(runmod, "get_loader", _fake_loader_factory)
    monkeypatch.setattr(runmod, "get_saver", lambda kind: _fake_saver)
    monkeypatch.setattr(runmod, "build_steps_from_config", lambda specs: ["S:cfg"])
    monkeypatch.setattr(runmod, "run_pipeline", lambda frames, steps: frames)

    rc = runmod.main(["--config", str(cfg_path)])
    assert rc == 0
