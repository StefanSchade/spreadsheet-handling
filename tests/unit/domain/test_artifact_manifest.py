"""Tests for the artifact manifest aggregation step (FTR-GENERATED-ARTIFACT-MANIFEST-P4A)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.domain.artifact_manifest import write_artifact_manifest
from spreadsheet_handling.pipeline import REGISTRY, build_steps_from_config, run_pipeline
from spreadsheet_handling.pipeline.types import StepRegistration

pytestmark = pytest.mark.ftr("FTR-GENERATED-ARTIFACT-MANIFEST-P4A")


def _make_kv_report(*paths: str, frame: str = "resources") -> pd.DataFrame:
    """Minimal key_value_resources style report: path, frame, rows, bytes."""
    return pd.DataFrame(
        [{"path": p, "frame": frame, "rows": 2, "bytes": 20} for p in paths],
        columns=["path", "frame", "rows", "bytes"],
    )


def _make_yaml_report(*paths: str, frame: str = "config") -> pd.DataFrame:
    """Minimal structured_yaml style report: path, frame, root, rows, bytes."""
    return pd.DataFrame(
        [{"path": p, "frame": frame, "root": "mapping", "rows": 3, "bytes": 30} for p in paths],
        columns=["path", "frame", "root", "rows", "bytes"],
    )


def test_merges_multiple_report_frames_deterministically(tmp_path: Path) -> None:
    frames = {
        "kv_report": _make_kv_report("b.properties"),
        "yaml_report": _make_yaml_report("a.yml"),
    }

    out = write_artifact_manifest(
        frames,
        reports=["kv_report", "yaml_report"],
        output="manifest",
    )

    df = out["manifest"]
    assert list(df.columns) == ["path", "artifact_kind", "writer_step", "source_frames", "row_count", "checksum", "status"]
    assert list(df["path"]) == ["a.yml", "b.properties"]  # sorted by path


def test_manifest_ordering_independent_of_input_frame_order(tmp_path: Path) -> None:
    frames_a = {
        "r1": _make_kv_report("z.properties"),
        "r2": _make_kv_report("a.properties"),
    }
    frames_b = {
        "r1": _make_kv_report("a.properties"),
        "r2": _make_kv_report("z.properties"),
    }

    out_a = write_artifact_manifest(frames_a, reports=["r1", "r2"])
    out_b = write_artifact_manifest(frames_b, reports=["r1", "r2"])

    paths_a = list(out_a["generated_artifacts"]["path"])
    paths_b = list(out_b["generated_artifacts"]["path"])
    assert paths_a == paths_b == ["a.properties", "z.properties"]


def test_duplicate_path_raises_clear_error() -> None:
    frames = {
        "r1": _make_kv_report("same.properties"),
        "r2": _make_kv_report("same.properties"),
    }

    with pytest.raises(ValueError, match="Duplicate artifact path"):
        write_artifact_manifest(frames, reports=["r1", "r2"])


def test_missing_report_frame_raises_clear_error() -> None:
    frames: dict = {}

    with pytest.raises(KeyError, match="not found"):
        write_artifact_manifest(frames, reports=["nonexistent_frame"])


def test_source_frames_is_list_from_single_frame_column() -> None:
    frames = {"r": _make_kv_report("out.properties", frame="my_data")}

    out = write_artifact_manifest(frames, reports=["r"])
    source_frames = out["generated_artifacts"]["source_frames"].iloc[0]
    assert source_frames == ["my_data"]


def test_annotated_report_spec_populates_writer_step_and_artifact_kind() -> None:
    frames = {"r": _make_kv_report("messages.properties")}

    out = write_artifact_manifest(
        frames,
        reports=[{
            "frame": "r",
            "writer_step": "write_key_value_resources",
            "artifact_kind": "properties",
        }],
    )

    df = out["generated_artifacts"]
    assert df["writer_step"].iloc[0] == "write_key_value_resources"
    assert df["artifact_kind"].iloc[0] == "properties"


def test_checksum_is_content_based_and_stable(tmp_path: Path) -> None:
    artifact = tmp_path / "out.properties"
    artifact.write_bytes(b"key=value\n")
    expected = hashlib.sha256(b"key=value\n").hexdigest()

    frames = {"r": _make_kv_report("out.properties")}
    out = write_artifact_manifest(
        frames,
        reports=["r"],
        output_dir=tmp_path,
        checksum="sha256",
    )

    df = out["generated_artifacts"]
    assert df["checksum"].iloc[0] == expected

    # second run produces identical checksum
    out2 = write_artifact_manifest(frames, reports=["r"], output_dir=tmp_path, checksum="sha256")
    assert out2["generated_artifacts"]["checksum"].iloc[0] == expected


def test_yaml_manifest_file_is_written(tmp_path: Path) -> None:
    frames = {"r": _make_kv_report("out.properties")}

    write_artifact_manifest(
        frames,
        reports=["r"],
        output_dir=tmp_path,
        manifest_path="manifest.yml",
    )

    manifest_file = tmp_path / "manifest.yml"
    assert manifest_file.exists()
    records = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
    assert isinstance(records, list)
    assert records[0]["path"] == "out.properties"
    assert records[0]["source_frames"] == ["resources"]
    assert records[0]["status"] == "success"


def test_json_manifest_file_is_written(tmp_path: Path) -> None:
    frames = {"r": _make_kv_report("out.properties")}

    write_artifact_manifest(
        frames,
        reports=["r"],
        output_dir=tmp_path,
        manifest_path="manifest.json",
    )

    manifest_file = tmp_path / "manifest.json"
    assert manifest_file.exists()
    records = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert isinstance(records, list)
    assert records[0]["path"] == "out.properties"
    assert records[0]["source_frames"] == ["resources"]


def test_manifest_file_uses_unix_newlines(tmp_path: Path) -> None:
    frames = {"r": _make_kv_report("a.properties"), }

    write_artifact_manifest(
        frames,
        reports=["r"],
        output_dir=tmp_path,
        manifest_path="manifest.yml",
    )

    raw = (tmp_path / "manifest.yml").read_bytes()
    assert b"\r\n" not in raw


def test_manifest_path_traversal_is_rejected(tmp_path: Path) -> None:
    frames = {"r": _make_kv_report("out.properties")}

    with pytest.raises(ValueError, match="escapes output_dir"):
        write_artifact_manifest(
            frames,
            reports=["r"],
            output_dir=tmp_path,
            manifest_path="../escaped.yml",
        )


def test_absolute_manifest_path_is_rejected(tmp_path: Path) -> None:
    frames = {"r": _make_kv_report("out.properties")}

    with pytest.raises(ValueError, match="must be relative"):
        write_artifact_manifest(
            frames,
            reports=["r"],
            output_dir=tmp_path,
            manifest_path=str(tmp_path / "manifest.yml"),
        )


def test_checksum_requires_output_dir() -> None:
    frames = {"r": _make_kv_report("out.properties")}

    with pytest.raises(ValueError, match="output_dir is required"):
        write_artifact_manifest(frames, reports=["r"], checksum="sha256")


def test_manifest_path_requires_output_dir() -> None:
    frames = {"r": _make_kv_report("out.properties")}

    with pytest.raises(ValueError, match="output_dir is required"):
        write_artifact_manifest(frames, reports=["r"], manifest_path="manifest.yml")


def test_absolute_reported_artifact_path_is_rejected_without_output_dir(tmp_path: Path) -> None:
    frames = {"r": _make_kv_report(str(tmp_path / "outside.txt"))}

    with pytest.raises(ValueError, match="must be relative"):
        write_artifact_manifest(frames, reports=["r"])


def test_parent_segment_reported_artifact_path_is_rejected_without_output_dir() -> None:
    frames = {"r": _make_kv_report("../outside.txt")}

    with pytest.raises(ValueError, match="must not contain"):
        write_artifact_manifest(frames, reports=["r"])


def test_normal_relative_reported_artifact_path_works_without_output_dir() -> None:
    frames = {"r": _make_kv_report("nested/out.properties")}

    out = write_artifact_manifest(frames, reports=["r"])

    assert list(out["generated_artifacts"]["path"]) == ["nested/out.properties"]


def test_reported_artifact_path_traversal_is_rejected_with_checksum(tmp_path: Path) -> None:
    frames = {"r": _make_kv_report("../outside.txt")}

    with pytest.raises(ValueError, match="escapes output_dir"):
        write_artifact_manifest(
            frames,
            reports=["r"],
            output_dir=tmp_path,
            checksum="sha256",
        )


def test_reported_artifact_path_traversal_is_rejected_without_checksum(tmp_path: Path) -> None:
    frames = {"r": _make_kv_report("../outside.txt")}

    with pytest.raises(ValueError, match="escapes output_dir"):
        write_artifact_manifest(
            frames,
            reports=["r"],
            output_dir=tmp_path,
        )


def test_duplicate_detection_catches_normalized_equivalent_paths(tmp_path: Path) -> None:
    frames = {
        "r1": _make_kv_report("nested/x.txt"),
        "r2": _make_kv_report("nested\\x.txt"),
    }

    with pytest.raises(ValueError, match="Duplicate artifact path"):
        write_artifact_manifest(frames, reports=["r1", "r2"], output_dir=tmp_path)


def test_step_is_config_addressable(tmp_path: Path) -> None:
    frames = {
        "yaml_report": _make_yaml_report("config.yml"),
        "kv_report": _make_kv_report("labels.properties"),
    }

    steps = build_steps_from_config([{
        "step": "write_artifact_manifest",
        "reports": ["yaml_report", "kv_report"],
        "output": "my_manifest",
    }])

    assert isinstance(REGISTRY["write_artifact_manifest"], StepRegistration)
    assert steps[0].config["target"].endswith(":write_artifact_manifest")

    out = run_pipeline(frames, steps)
    assert "my_manifest" in out
    df = out["my_manifest"]
    assert set(df["path"]) == {"config.yml", "labels.properties"}
