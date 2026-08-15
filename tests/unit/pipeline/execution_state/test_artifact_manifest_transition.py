"""M1 artifact manifest source_frames role (FTR section 16; test matrix item M).

Also covers the independent E4 implementation review's Important I2 finding:
the manifest role's explicit consume/whole-frame-cleanup/unsupported-sink
exit representation, analogous to the FormulaSpec/GroupedMatrix exit chain.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.domain.artifact_manifest import write_artifact_manifest
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    MANIFEST_ADAPTER_SINK_KIND,
    ArtifactManifestCertificate,
    ArtifactManifestSourceFramesRole,
    TransitionEffect,
    Uncertified,
    artifact_manifest_role,
    classify_artifact_manifest_step,
    consume_manifest_at_sink,
    terminate_roles_removed_by_cleanup,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def test_exact_configuration_produces_the_expected_descriptor() -> None:
    step = build_steps_from_config(
        [{"step": "write_artifact_manifest", "reports": ["written_files"], "output": "manifest"}]
    )[0]
    certificate = classify_artifact_manifest_step(step)
    assert certificate == ArtifactManifestCertificate(output="manifest", writes_manifest_file=False)
    assert artifact_manifest_role(certificate) == ArtifactManifestSourceFramesRole(frame="manifest")


def test_default_output_frame_name_is_certified() -> None:
    step = build_steps_from_config(
        [{"step": "write_artifact_manifest", "reports": ["written_files"]}]
    )[0]
    certificate = classify_artifact_manifest_step(step)
    assert isinstance(certificate, ArtifactManifestCertificate)
    assert certificate.output == "generated_artifacts"


def test_unknown_option_is_uncertified() -> None:
    step = build_steps_from_config(
        [
            {
                "step": "write_artifact_manifest",
                "reports": ["written_files"],
                "output": "manifest",
                "unreviewed_extra_flag": True,
            }
        ]
    )[0]
    result = classify_artifact_manifest_step(step)
    assert result == Uncertified(reason="unknown_option", detail="write_artifact_manifest")


def test_runtime_proof_source_frames_is_a_one_level_list_of_strings() -> None:
    written_files = pd.DataFrame(
        {
            "path": ["out/a.json"],
            "frame": ["frame_a"],
            "rows": [3],
        }
    )
    out = write_artifact_manifest(
        {"written_files": written_files},
        reports=["written_files"],
        output="manifest",
    )
    manifest = out["manifest"]
    cell = manifest["source_frames"].iloc[0]
    assert type(cell) is list
    assert all(type(item) is str for item in cell)


def test_writes_manifest_file_true_only_when_both_manifest_path_and_output_dir_set() -> None:
    with_both = build_steps_from_config(
        [
            {
                "step": "write_artifact_manifest",
                "reports": ["written_files"],
                "output": "manifest",
                "output_dir": "build/out",
                "manifest_path": "manifest.json",
            }
        ]
    )[0]
    certificate = classify_artifact_manifest_step(with_both)
    assert isinstance(certificate, ArtifactManifestCertificate)
    assert certificate.writes_manifest_file is True

    only_output_dir = build_steps_from_config(
        [
            {
                "step": "write_artifact_manifest",
                "reports": ["written_files"],
                "output": "manifest",
                "output_dir": "build/out",
            }
        ]
    )[0]
    certificate2 = classify_artifact_manifest_step(only_output_dir)
    assert isinstance(certificate2, ArtifactManifestCertificate)
    assert certificate2.writes_manifest_file is False


def test_capable_adapter_consumes_the_role() -> None:
    step = build_steps_from_config(
        [
            {
                "step": "write_artifact_manifest",
                "reports": ["written_files"],
                "output": "manifest",
                "output_dir": "build/out",
                "manifest_path": "manifest.json",
            }
        ]
    )[0]
    certificate = classify_artifact_manifest_step(step)
    assert isinstance(certificate, ArtifactManifestCertificate)
    role = artifact_manifest_role(certificate)

    result = consume_manifest_at_sink(certificate, role, sink_kind=MANIFEST_ADAPTER_SINK_KIND)
    assert result == ArtifactManifestSourceFramesRole(
        frame="manifest", effect=TransitionEffect.CONSUME_TERMINATE
    )


def test_unsupported_sink_does_not_silently_certify_consumption() -> None:
    step = build_steps_from_config(
        [
            {
                "step": "write_artifact_manifest",
                "reports": ["written_files"],
                "output": "manifest",
                "output_dir": "build/out",
                "manifest_path": "manifest.json",
            }
        ]
    )[0]
    certificate = classify_artifact_manifest_step(step)
    assert isinstance(certificate, ArtifactManifestCertificate)
    role = artifact_manifest_role(certificate)

    result = consume_manifest_at_sink(certificate, role, sink_kind="xlsx")
    assert result == Uncertified(reason="uncovered_configuration", detail="sink_kind")


def test_consume_rejects_a_role_from_an_unrelated_certificate() -> None:
    """I2 residual reproduction (independent E4 implementation review
    `ad700f0`, section 16.5): a certificate for frame A must not authorize
    termination of an unrelated role at frame B."""
    cert_a = ArtifactManifestCertificate(output="A", writes_manifest_file=True)
    role_b = ArtifactManifestSourceFramesRole(frame="B")

    result = consume_manifest_at_sink(cert_a, role_b, sink_kind=MANIFEST_ADAPTER_SINK_KIND)
    assert result == Uncertified(reason="mismatched_composition", detail="output")


def test_consume_rejects_a_role_with_the_wrong_column() -> None:
    cert = ArtifactManifestCertificate(output="manifest", writes_manifest_file=True)
    wrong_column_role = ArtifactManifestSourceFramesRole(frame="manifest", column="other")

    result = consume_manifest_at_sink(cert, wrong_column_role, sink_kind=MANIFEST_ADAPTER_SINK_KIND)
    assert result == Uncertified(reason="mismatched_composition", detail="column")


def test_consume_accepts_the_role_the_certificate_actually_introduced() -> None:
    step = build_steps_from_config(
        [
            {
                "step": "write_artifact_manifest",
                "reports": ["written_files"],
                "output": "manifest",
                "output_dir": "build/out",
                "manifest_path": "manifest.json",
            }
        ]
    )[0]
    certificate = classify_artifact_manifest_step(step)
    assert isinstance(certificate, ArtifactManifestCertificate)
    role = artifact_manifest_role(certificate)

    result = consume_manifest_at_sink(certificate, role, sink_kind=MANIFEST_ADAPTER_SINK_KIND)
    assert result == ArtifactManifestSourceFramesRole(
        frame="manifest", effect=TransitionEffect.CONSUME_TERMINATE
    )


def test_same_adapter_kind_without_configured_write_does_not_certify_consumption() -> None:
    # The role was introduced, but this exact invocation never configured a
    # write (no manifest_path/output_dir) -- there is nothing to consume.
    step = build_steps_from_config(
        [{"step": "write_artifact_manifest", "reports": ["written_files"], "output": "manifest"}]
    )[0]
    certificate = classify_artifact_manifest_step(step)
    assert isinstance(certificate, ArtifactManifestCertificate)
    role = artifact_manifest_role(certificate)

    result = consume_manifest_at_sink(certificate, role, sink_kind=MANIFEST_ADAPTER_SINK_KIND)
    assert result == Uncertified(reason="uncovered_configuration", detail="sink_kind")


def test_whole_frame_cleanup_terminates_the_manifest_role() -> None:
    step = build_steps_from_config(
        [{"step": "write_artifact_manifest", "reports": ["written_files"], "output": "manifest"}]
    )[0]
    certificate = classify_artifact_manifest_step(step)
    assert isinstance(certificate, ArtifactManifestCertificate)
    role = artifact_manifest_role(certificate)

    kept = terminate_roles_removed_by_cleanup((role,), removed_frames=frozenset({"manifest"}))
    assert kept == ()

    kept_other = terminate_roles_removed_by_cleanup((role,), removed_frames=frozenset({"unrelated"}))
    assert kept_other == (role,)


def test_runtime_proof_adapter_actually_writes_the_configured_manifest_file() -> None:
    """Confirms `writes_manifest_file` corresponds to real writer behavior:
    when both options are set, the reviewed adapter genuinely writes a
    manifest file to disk."""
    written_files = pd.DataFrame({"path": ["out/a.json"], "frame": ["frame_a"], "rows": [1]})
    with tempfile.TemporaryDirectory() as tmp:
        write_artifact_manifest(
            {"written_files": written_files},
            reports=["written_files"],
            output="manifest",
            output_dir=tmp,
            manifest_path="manifest.json",
        )
        assert (Path(tmp) / "manifest.json").exists()
