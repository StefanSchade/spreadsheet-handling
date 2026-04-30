import types

import pytest

import spreadsheet_handling.cli.apps.run as runmod

pytestmark = pytest.mark.ftr("FTR-TEST-NAMING-AND-CONVENTIONS-P3C")


class _Args(types.SimpleNamespace):
    pass


def test_load_config_ignores_inline_io_when_steps_file_is_missing(monkeypatch):
    """If --steps points to a non-existing file, the guard should skip inline IO."""
    args = _Args(config=None, steps="steps.yml")
    monkeypatch.setattr(runmod.os.path, "exists", lambda p: False)
    monkeypatch.setattr(
        runmod,
        "_maybe_load_inline_config_from_steps_yaml",
        lambda p: {"io": "SHOULD_NOT_BE_USED"},
    )
    cfg = runmod._load_config(args)
    assert cfg == {}


def test_load_config_uses_inline_io_when_steps_file_exists(tmp_path, monkeypatch):
    """If --steps exists, inline IO should be accepted into config."""
    steps_path = tmp_path / "steps.yml"
    steps_path.write_text("irrelevant: true\n", encoding="utf-8")

    args = _Args(config=None, steps=str(steps_path))

    monkeypatch.setattr(
        runmod,
        "_maybe_load_inline_config_from_steps_yaml",
        lambda p: {
            "io": {
                "input": {"kind": "json_dir", "path": "in"},
                "output": {"kind": "json_dir", "path": "out"},
            }
        },
    )

    cfg = runmod._load_config(args)
    assert cfg == {
        "io": {
            "input": {"kind": "json_dir", "path": "in"},
            "output": {"kind": "json_dir", "path": "out"},
        }
    }
