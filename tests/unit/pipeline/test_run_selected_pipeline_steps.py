import pytest

import spreadsheet_handling.cli.apps.run as runmod

@pytest.fixture(autouse=True)
def patch_builders(monkeypatch):
    called = {"yaml": None, "config": None}
    def fake_yaml(p):
        called["yaml"] = p; return ["S:yaml"]
    def fake_config(specs):
        called["config"] = specs; return ["S:cfg"]
    monkeypatch.setattr(runmod, "build_steps_from_yaml", fake_yaml)
    monkeypatch.setattr(runmod, "build_steps_from_config", fake_config)
    return called

def test_steps_yaml_wins(patch_builders):
    cfg = {}  # irrelevant
    out = runmod._select_pipeline_steps(cfg, pipeline_name=None, steps_yaml="steps.yml", profile=None)
    assert out == ["S:yaml"]
    assert patch_builders["yaml"] == "steps.yml"
    assert patch_builders["config"] is None

def test_pipeline_name_from_config(patch_builders):
    cfg = {"pipelines": {"clean": [{"factory":"x","args":{}}]}}
    out = runmod._select_pipeline_steps(cfg, pipeline_name="clean", steps_yaml=None, profile=None)
    assert out == ["S:cfg"]
    assert patch_builders["config"] == [{"factory":"x","args":{}}]

def test_pipeline_from_profile(patch_builders):
    cfg = {
        "io": {"profiles": {"local": {"pipeline": "clean"}}},
        "pipelines": {"clean": [{"factory":"x","args":{}}]}
    }
    out = runmod._select_pipeline_steps(cfg, pipeline_name=None, steps_yaml=None, profile="local")
    assert out == ["S:cfg"]

def test_fallback_top_level_pipeline(patch_builders):
    cfg = {"pipeline": [{"factory":"y","args":{"a":1}}]}
    out = runmod._select_pipeline_steps(cfg, pipeline_name=None, steps_yaml=None, profile=None)
    assert out == ["S:cfg"]
    assert patch_builders["config"] == [{"factory":"y","args":{"a":1}}]

def test_unknown_pipeline_raises():
    cfg = {"pipelines": {"clean": []}}
    with pytest.raises(SystemExit) as e:
        runmod._select_pipeline_steps(cfg, pipeline_name="nope", steps_yaml=None, profile=None)
    assert "Unknown pipeline 'nope'" in str(e.value)

def test_profile_refers_unknown_pipeline_raises():
    cfg = {"io": {"profiles": {"p": {"pipeline": "missing"}}}, "pipelines": {"clean": []}}
    with pytest.raises(SystemExit) as e:
        runmod._select_pipeline_steps(cfg, pipeline_name=None, steps_yaml=None, profile="p")
    assert "refers to unknown pipeline 'missing'" in str(e.value)
