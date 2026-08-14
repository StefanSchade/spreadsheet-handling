"""M1 artifact manifest source_frames role (FTR section 16; test matrix item M)."""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.artifact_manifest import write_artifact_manifest
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    ArtifactManifestCertificate,
    ArtifactManifestSourceFramesRole,
    Uncertified,
    artifact_manifest_role,
    classify_artifact_manifest_step,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def test_exact_configuration_produces_the_expected_descriptor() -> None:
    step = build_steps_from_config(
        [{"step": "write_artifact_manifest", "reports": ["written_files"], "output": "manifest"}]
    )[0]
    certificate = classify_artifact_manifest_step(step)
    assert certificate == ArtifactManifestCertificate(output="manifest")
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
