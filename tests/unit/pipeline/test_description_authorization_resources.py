"""E7 registered resource-selector authorization evidence."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import spreadsheet_handling.pipeline.steps as steps_module
from spreadsheet_handling.pipeline import (
    DescriptionAuthorizationError,
    LessTrustedDescriptionAuthorization,
    build_steps_from_config,
    run_pipeline,
)


pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _policy(step: str, constraints: dict) -> LessTrustedDescriptionAuthorization:
    return LessTrustedDescriptionAuthorization.from_mapping(
        {"registered_steps": {step: constraints}}
    )


def _build(spec: dict, policy: LessTrustedDescriptionAuthorization):
    return build_steps_from_config([spec], description_authorization=policy)[0]


def _assert_kind(kind: str, callback) -> DescriptionAuthorizationError:
    with pytest.raises(DescriptionAuthorizationError) as excinfo:
        callback()
    assert excinfo.value.kind == kind
    return excinfo.value


def test_inline_apply_overrides_is_authorized_and_executes() -> None:
    step = _build(
        {
            "step": "apply_overrides",
            "overrides": {"defaults": {"freeze_header": True}},
        },
        _policy("apply_overrides", {}),
    )
    frames = {"Sheet": pd.DataFrame({"id": [1]})}
    out = run_pipeline(frames, [step])
    assert out["_meta"]["freeze_header"] is True


@pytest.mark.parametrize("path", ["relative.yml", "/absolute.yml", ""])
def test_apply_overrides_path_is_categorically_denied(path: str) -> None:
    _assert_kind(
        "forbidden_resource_selector",
        lambda: _build(
            {"step": "apply_overrides", "overrides_path": path},
            _policy("apply_overrides", {}),
        ),
    )


def test_apply_overrides_pathlike_rejects_safely() -> None:
    _assert_kind(
        "malformed_description",
        lambda: _build(
            {"step": "apply_overrides", "overrides_path": Path("x.yml")},
            _policy("apply_overrides", {}),
        ),
    )


def test_apply_overrides_denial_precedes_target_binding_and_path_exists(monkeypatch) -> None:
    monkeypatch.setattr(
        steps_module,
        "resolve_configuration_callable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("target bound")),
    )
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: (_ for _ in ()).throw(AssertionError("path inspected")),
    )
    _assert_kind(
        "forbidden_resource_selector",
        lambda: _build(
            {"step": "apply_overrides", "overrides_path": "x.yml"},
            _policy("apply_overrides", {}),
        ),
    )


def test_structured_yaml_exact_root_and_contained_static_path_are_bound(tmp_path) -> None:
    root = tmp_path / "root"
    step = _build(
        {
            "step": "write_structured_yaml",
            "output_dir": str(root),
            "files": [{"path": "nested/out.yml"}],
        },
        _policy("write_structured_yaml", {"output_roots": [str(root.resolve())]}),
    )
    assert step.config["output_dir"] == str(root.resolve())
    assert step.config["files"][0]["path"] == "nested/out.yml"


def test_structured_yaml_unlisted_root_denies_before_internal_target(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        steps_module,
        "resolve_configuration_callable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("target bound")),
    )
    allowed = tmp_path / "allowed"
    _assert_kind(
        "forbidden_resource_selector",
        lambda: _build(
            {
                "step": "write_structured_yaml",
                "output_dir": str(tmp_path / "sibling"),
                "files": [{"path": "out.yml"}],
            },
            _policy("write_structured_yaml", {"output_roots": [str(allowed.resolve())]}),
        ),
    )


@pytest.mark.parametrize("path", ["../escape.yml", "/absolute.yml"])
def test_structured_yaml_static_escape_denies_before_binding(path, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        steps_module,
        "resolve_configuration_callable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("target bound")),
    )
    root = tmp_path / "root"
    _assert_kind(
        "forbidden_resource_selector",
        lambda: _build(
            {
                "step": "write_structured_yaml",
                "output_dir": str(root),
                "files": [{"path": path}],
            },
            _policy("write_structured_yaml", {"output_roots": [str(root.resolve())]}),
        ),
    )


def test_structured_yaml_existing_symlink_escape_denies(tmp_path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    _assert_kind(
        "forbidden_resource_selector",
        lambda: _build(
            {
                "step": "write_structured_yaml",
                "output_dir": str(root),
                "files": [{"path": "link/out.yml"}],
            },
            _policy("write_structured_yaml", {"output_roots": [str(root.resolve())]}),
        ),
    )


def test_key_value_writer_exact_root_and_string_pattern_are_bound(tmp_path) -> None:
    root = tmp_path / "root"
    step = _build(
        {
            "step": "write_key_value_resources",
            "output_dir": str(root),
            "file_pattern": "{locale}.properties",
        },
        _policy("write_key_value_resources", {"output_roots": [str(root.resolve())]}),
    )
    assert step.config["output_dir"] == str(root.resolve())


def test_key_value_writer_unlisted_root_is_denied(tmp_path) -> None:
    root = tmp_path / "root"
    _assert_kind(
        "forbidden_resource_selector",
        lambda: _build(
            {
                "step": "write_key_value_resources",
                "output_dir": str(tmp_path / "other"),
                "file_pattern": "out.properties",
            },
            _policy("write_key_value_resources", {"output_roots": [str(root.resolve())]}),
        ),
    )


def test_key_value_writer_malformed_pattern_fails_without_string_hook(tmp_path) -> None:
    class Pattern:
        calls = 0

        def __str__(self):
            type(self).calls += 1
            raise AssertionError

    root = tmp_path / "root"
    _assert_kind(
        "malformed_description",
        lambda: _build(
            {
                "step": "write_key_value_resources",
                "output_dir": str(root),
                "file_pattern": Pattern(),
            },
            _policy("write_key_value_resources", {"output_roots": [str(root.resolve())]}),
        ),
    )
    assert Pattern.calls == 0


def test_key_value_runtime_containment_remains_load_bearing(tmp_path) -> None:
    root = tmp_path / "root"
    step = _build(
        {
            "step": "write_key_value_resources",
            "source": "values",
            "output_dir": str(root),
            "file_pattern": "{locale}.properties",
            "key": "key",
            "value": "value",
        },
        _policy("write_key_value_resources", {"output_roots": [str(root.resolve())]}),
    )
    frames = {
        "values": pd.DataFrame(
            [{"locale": "../escape", "key": "hello", "value": "Hello"}]
        )
    }
    with pytest.raises(ValueError, match="escapes output_dir"):
        run_pipeline(frames, [step])


def test_manifest_in_memory_only_mode_needs_no_root() -> None:
    step = _build(
        {"step": "write_artifact_manifest", "reports": ["report"]},
        _policy("write_artifact_manifest", {}),
    )
    frames = {"report": pd.DataFrame([{"path": "inside.txt"}])}
    out = run_pipeline(frames, [step])
    assert out["generated_artifacts"]["path"].tolist() == ["inside.txt"]


def test_manifest_exact_root_write_and_contained_manifest_path(tmp_path) -> None:
    root = tmp_path / "root"
    step = _build(
        {
            "step": "write_artifact_manifest",
            "reports": ["report"],
            "output_dir": str(root),
            "manifest_path": "manifests/files.yml",
        },
        _policy("write_artifact_manifest", {"output_roots": [str(root.resolve())]}),
    )
    out = run_pipeline({"report": pd.DataFrame([{"path": "inside.txt"}])}, [step])
    assert out["generated_artifacts"]["path"].tolist() == ["inside.txt"]
    assert (root / "manifests/files.yml").exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"output_dir": "sibling"},
        {"manifest_path": "../escape.yml"},
    ],
)
def test_manifest_unlisted_root_or_manifest_escape_denies(tmp_path, overrides) -> None:
    root = tmp_path / "root"
    spec = {
        "step": "write_artifact_manifest",
        "reports": [],
        "output_dir": str(root),
        **overrides,
    }
    if overrides.get("output_dir") == "sibling":
        spec["output_dir"] = str(tmp_path / "sibling")
    _assert_kind(
        "forbidden_resource_selector",
        lambda: _build(
            spec,
            _policy("write_artifact_manifest", {"output_roots": [str(root.resolve())]}),
        ),
    )


def test_manifest_sha256_denies_without_read_permission_before_read_bytes(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "root"
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda self: (_ for _ in ()).throw(AssertionError("read occurred")),
    )
    _assert_kind(
        "forbidden_resource_selector",
        lambda: _build(
            {
                "step": "write_artifact_manifest",
                "reports": [],
                "output_dir": str(root),
                "checksum": "sha256",
            },
            _policy("write_artifact_manifest", {"output_roots": [str(root.resolve())]}),
        ),
    )


def test_manifest_sha256_with_explicit_read_permission(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "inside.txt").write_bytes(b"content")
    step = _build(
        {
            "step": "write_artifact_manifest",
            "reports": ["report"],
            "output_dir": str(root),
            "checksum": "sha256",
        },
        _policy(
            "write_artifact_manifest",
            {"output_roots": [str(root.resolve())], "allow_checksum_reads": True},
        ),
    )
    out = run_pipeline({"report": pd.DataFrame([{"path": "inside.txt"}])}, [step])
    assert len(out["generated_artifacts"].iloc[0]["checksum"]) == 64


def test_manifest_report_escape_denies_before_read_bytes(monkeypatch, tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda self: (_ for _ in ()).throw(AssertionError("read occurred")),
    )
    step = _build(
        {
            "step": "write_artifact_manifest",
            "reports": ["report"],
            "output_dir": str(root),
            "checksum": "sha256",
        },
        _policy(
            "write_artifact_manifest",
            {"output_roots": [str(root.resolve())], "allow_checksum_reads": True},
        ),
    )
    with pytest.raises(ValueError, match="escapes output_dir"):
        run_pipeline({"report": pd.DataFrame([{"path": "../outside.txt"}])}, [step])


def test_relative_output_dir_is_frozen_against_later_cwd_change(tmp_path, monkeypatch) -> None:
    original = tmp_path / "original"
    later = tmp_path / "later"
    original.mkdir()
    later.mkdir()
    monkeypatch.chdir(original)
    step = _build(
        {
            "step": "write_key_value_resources",
            "source": "values",
            "output_dir": ".",
            "file_pattern": "out.properties",
            "key": "key",
            "value": "value",
        },
        _policy("write_key_value_resources", {"output_roots": [str(original.resolve())]}),
    )
    monkeypatch.chdir(later)
    run_pipeline({"values": pd.DataFrame([{"key": "x", "value": "y"}])}, [step])
    assert (original / "out.properties").exists()
    assert not (later / "out.properties").exists()
