import pytest
import pandas as pd
from spreadsheet_handling.cli import run as run_mod


class DummyLoaderSaver:
    def __init__(self):
        self.loaded_path = None
        self.saved_path = None
        self.saved_frames = None

    def loader(self, path: str):
        self.loaded_path = path
        return {"A": pd.DataFrame({"id": ["1"], "name": ["x"]})}

    def saver(self, frames, path: str):
        self.saved_path = path
        self.saved_frames = frames


@pytest.fixture(autouse=True)
def patch_router(monkeypatch):
    dummy = DummyLoaderSaver()
    monkeypatch.setattr(run_mod, "get_loader", lambda kind: dummy.loader)
    monkeypatch.setattr(run_mod, "get_saver",  lambda kind: dummy.saver)
    return dummy


def test_cli_runs_basic(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        """
io:
  input: { kind: csv_dir, path: in_dir }
  output: { kind: csv_dir, path: out_dir }
pipeline:
  - step: drop_helpers
    prefix: "_"
        """,
        encoding="utf-8",
    )
    rc = run_mod.main(["--config", str(cfg)])
    assert rc == 0


def test_cli_runs_with_profile_and_pipeline(tmp_path):
    cfg = tmp_path / "pipelines.yml"
    cfg.write_text(
        """
io:
  profiles:
    demo:
      input:  { kind: csv_dir, path: in_dir }
      output: { kind: csv_dir, path: out_dir }
pipelines:
  basic:
    - step: drop_helpers
      prefix: "_"
        """,
        encoding="utf-8",
    )
    rc = run_mod.main(["--config", str(cfg), "--profile", "demo", "--pipeline", "basic"])
    assert rc == 0


def test_cli_overrides_paths(tmp_path):
    cfg = tmp_path / "pipelines.yml"
    cfg.write_text(
        """
io:
  profiles:
    demo:
      input:  { kind: csv_dir, path: SHOULD_NOT_BE_USED }
      output: { kind: csv_dir, path: SHOULD_NOT_BE_USED }
pipelines:
  basic:
    - step: drop_helpers
      prefix: "_"
        """,
        encoding="utf-8",
    )
    rc = run_mod.main([
        "--config", str(cfg),
        "--profile", "demo",
        "--pipeline", "basic",
        "--in-path", "OVERRIDDEN_IN",
        "--out-path", "OVERRIDDEN_OUT",
    ])
    assert rc == 0


def test_cli_fails_on_unknown_profile(tmp_path):
    cfg = tmp_path / "bad.yml"
    cfg.write_text("io: { profiles: {} }", encoding="utf-8")
    with pytest.raises(SystemExit):
        run_mod.main(["--config", str(cfg), "--profile", "nope"])


def test_cli_fails_on_missing_io(tmp_path):
    cfg = tmp_path / "bad.yml"
    cfg.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        run_mod.main(["--config", str(cfg)])
