# tests/unit/cli/test_run_load_config_inline_io.py
import types
import spreadsheet_handling.cli.apps.run as runmod

class _Args(types.SimpleNamespace): pass

def test__load_config_steps_guard_no_file(monkeypatch):
    """If --steps points to a non-existing file, the guard should skip inline IO."""
    args = _Args(config=None, steps="steps.yml")
    # Ensure exists() returns False to hit the guard
    monkeypatch.setattr(runmod.os.path, "exists", lambda p: False)
    # Even if the inner function would return IO, it must not be called
    monkeypatch.setattr(runmod, "_maybe_load_inline_config_from_steps_yaml", lambda p: {"io": "SHOULD_NOT_BE_USED"})
    cfg = runmod._load_config(args)
    assert cfg == {}  # guard kept us from reading inline io

def test__load_config_uses_inline_io_when_file_exists(tmp_path, monkeypatch):
    """If --steps exists, inline IO should be accepted into config."""
    steps_path = tmp_path / "steps.yml"
    steps_path.write_text("irrelevant: true\n", encoding="utf-8")

    args = _Args(config=None, steps=str(steps_path))

    # Return an inline io block; we don't care about file content here
    monkeypatch.setattr(
        runmod, "_maybe_load_inline_config_from_steps_yaml",
        lambda p: {"io": {"input": {"kind": "json_dir", "path": "in"},
                          "output": {"kind": "json_dir", "path": "out"}}}
    )

    cfg = runmod._load_config(args)
    assert cfg == {"io": {"input": {"kind": "json_dir", "path": "in"},
                          "output": {"kind": "json_dir", "path": "out"}}}
