import spreadsheet_handling.cli.apps.run as runmod
import spreadsheet_handling.application.orchestrator as orch_mod


def test_main_with_real_steps_file(tmp_path, monkeypatch):
    steps_path = tmp_path / "steps.yml"
    steps_path.write_text("pipeline:\n  - step: identity\n")

    called = {}
    def _fake_orchestrate(**kwargs):
        called.update(kwargs)
        return {}

    monkeypatch.setattr(orch_mod, "orchestrate", _fake_orchestrate)
    monkeypatch.setattr(runmod, "orchestrate", _fake_orchestrate)

    rc = runmod.main([
        "--steps", str(steps_path),
        "--in-kind", "json_dir", "--in-path", "in",
        "--out-kind", "json_dir", "--out-path", "out",
    ])
    assert rc == 0
    assert called["input"]["kind"] == "json_dir"
    assert called["output"]["path"] == "out"


def test_main_with_top_level_pipeline(tmp_path, monkeypatch):
    cfg_path = tmp_path / "dummy.yml"
    cfg_path.write_text(
        "io:\n"
        "  input: {kind: json_dir, path: in}\n"
        "  output: {kind: json_dir, path: out}\n"
        "pipeline:\n"
        "  - step: identity\n"
    )

    called = {}
    def _fake_orchestrate(**kwargs):
        called.update(kwargs)
        return {}

    monkeypatch.setattr(orch_mod, "orchestrate", _fake_orchestrate)
    monkeypatch.setattr(runmod, "orchestrate", _fake_orchestrate)

    rc = runmod.main(["--config", str(cfg_path)])
    assert rc == 0
    assert called["input"]["kind"] == "json_dir"
