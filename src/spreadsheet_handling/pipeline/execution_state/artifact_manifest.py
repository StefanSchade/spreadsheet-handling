"""Artifact-manifest ``source_frames`` role (FTR section 10, "Artifact-manifest
role decision", Option M1; section 16).

An exact reviewed ``write_artifact_manifest`` invocation always establishes
``ArtifactManifestSourceFramesRole`` in column ``source_frames`` of its
declared ``output`` frame, under the complete existing manifest schema
(``domain.artifact_manifest.MANIFEST_COLUMNS``). Unlike the FormulaSpec/
GroupedMatrix transitions, no configuration branch changes *whether* the role
appears -- ``_normalize_report_rows`` always builds a one-level ``list[str]``
``source_frames`` cell -- so this classifier only needs to confirm the exact
target and extract the declared output frame name.
"""
from __future__ import annotations

from dataclasses import dataclass

from spreadsheet_handling.pipeline.types import BoundStep

from .bound_configuration import only_known_keys, snapshot_scalar
from .roles import ArtifactManifestSourceFramesRole
from .vocabulary import TransitionFootprint, Uncertified

WRITE_ARTIFACT_MANIFEST_TARGET = (
    "spreadsheet_handling.domain.artifact_manifest:write_artifact_manifest"
)

_KNOWN_OPTION_KEYS = frozenset(
    {"target", "reports", "output", "output_dir", "manifest_path", "checksum", "name"}
)

_DEFAULT_OUTPUT = "generated_artifacts"


@dataclass(frozen=True)
class ArtifactManifestCertificate:
    """The exact reviewed ``write_artifact_manifest`` output location."""

    output: str

    def footprint(self) -> TransitionFootprint:
        return TransitionFootprint(reads=frozenset(), writes=frozenset({self.output}), drops=frozenset())


def classify_artifact_manifest_step(step: BoundStep) -> ArtifactManifestCertificate | Uncertified:
    config = step.config
    if config.get("target") != WRITE_ARTIFACT_MANIFEST_TARGET:
        return Uncertified(reason="unrecognized_target")
    if not only_known_keys(config, known=_KNOWN_OPTION_KEYS):
        return Uncertified(reason="unknown_option", detail="write_artifact_manifest")
    output = snapshot_scalar(config.get("output", _DEFAULT_OUTPUT))
    if type(output) is not str or output == "":
        return Uncertified(reason="unsupported_configuration_value", detail="output")
    return ArtifactManifestCertificate(output=output)


def artifact_manifest_role(certificate: ArtifactManifestCertificate) -> ArtifactManifestSourceFramesRole:
    return ArtifactManifestSourceFramesRole(frame=certificate.output)


__all__ = [
    "WRITE_ARTIFACT_MANIFEST_TARGET",
    "ArtifactManifestCertificate",
    "classify_artifact_manifest_step",
    "artifact_manifest_role",
]
