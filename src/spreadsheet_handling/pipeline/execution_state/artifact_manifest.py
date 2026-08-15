"""Artifact-manifest ``source_frames`` role (FTR section 10, "Artifact-manifest
role decision", Option M1; section 16).

An exact reviewed ``write_artifact_manifest`` invocation always establishes
``ArtifactManifestSourceFramesRole`` in column ``source_frames`` of its
declared ``output`` frame, under the complete existing manifest schema
(``domain.artifact_manifest.MANIFEST_COLUMNS``). Unlike the FormulaSpec/
GroupedMatrix transitions, no configuration branch changes *whether* the role
appears -- ``_normalize_report_rows`` always builds a one-level ``list[str]``
``source_frames`` cell -- so the introduction classifier only needs to confirm
the exact target and extract the declared output frame name.

FTR section 10 names three exit possibilities for this role: consumption by
the manifest's own JSON/YAML artifact-record adapter
(``_manifest_to_records``/``_write_manifest_file``, run internally by
``write_artifact_manifest`` itself exactly when both ``manifest_path`` and
``output_dir`` are supplied), termination by exact whole-frame exclusion
(covered generically for every ``ControlledRole`` by
``roles.terminate_roles_removed_by_cleanup``), and deliberate rejection at
any other sink. ``consume_manifest_at_sink`` below represents the first and
third explicitly, alongside the introduction classifier, so E5 does not need
to reconstruct this reasoning from prose.
"""
from __future__ import annotations

from dataclasses import dataclass

from spreadsheet_handling.pipeline.types import BoundStep

from .bound_configuration import is_trusted_binding, only_known_keys, snapshot_scalar
from .roles import ArtifactManifestSourceFramesRole
from .vocabulary import TransitionEffect, TransitionFootprint, Uncertified

WRITE_ARTIFACT_MANIFEST_TARGET = (
    "spreadsheet_handling.domain.artifact_manifest:write_artifact_manifest"
)

_KNOWN_OPTION_KEYS = frozenset(
    {"target", "reports", "output", "output_dir", "manifest_path", "checksum", "name"}
)

_DEFAULT_OUTPUT = "generated_artifacts"

# The one maintained adapter that may consume ArtifactManifestSourceFrames:
# write_artifact_manifest's own internal JSON/YAML record writer, selected
# by supplying both manifest_path and output_dir. There is no separate
# sink/backend step for this role (unlike FormulaSpec's xlsx/ods adapters).
MANIFEST_ADAPTER_SINK_KIND = "artifact_manifest_writer"


@dataclass(frozen=True)
class ArtifactManifestCertificate:
    """The exact reviewed ``write_artifact_manifest`` configuration.

    ``writes_manifest_file`` is true exactly when both ``manifest_path`` and
    ``output_dir`` are supplied -- the same precondition
    ``domain.artifact_manifest.write_artifact_manifest`` itself uses to
    decide whether to call ``_manifest_to_records``/``_write_manifest_file``
    (its own internal adapter consume). It is presence-based only: the
    actual path values are not role-authority-relevant and remain the
    writer's own concern (it validates/raises on a malformed path at
    runtime).
    """

    output: str
    writes_manifest_file: bool

    def footprint(self) -> TransitionFootprint:
        return TransitionFootprint(reads=frozenset(), writes=frozenset({self.output}), drops=frozenset())


def classify_artifact_manifest_step(step: BoundStep) -> ArtifactManifestCertificate | Uncertified:
    if not is_trusted_binding(step):
        return Uncertified(reason="unauthenticated_binding")
    config = step.config
    if config.get("target") != WRITE_ARTIFACT_MANIFEST_TARGET:
        return Uncertified(reason="unrecognized_target")
    if not only_known_keys(config, known=_KNOWN_OPTION_KEYS):
        return Uncertified(reason="unknown_option", detail="write_artifact_manifest")
    output = snapshot_scalar(config.get("output", _DEFAULT_OUTPUT))
    if type(output) is not str or output == "":
        return Uncertified(reason="unsupported_configuration_value", detail="output")
    writes_manifest_file = (
        config.get("manifest_path") is not None and config.get("output_dir") is not None
    )
    return ArtifactManifestCertificate(output=output, writes_manifest_file=writes_manifest_file)


def artifact_manifest_role(certificate: ArtifactManifestCertificate) -> ArtifactManifestSourceFramesRole:
    return ArtifactManifestSourceFramesRole(frame=certificate.output)


def consume_manifest_at_sink(
    certificate: ArtifactManifestCertificate,
    role: ArtifactManifestSourceFramesRole,
    *,
    sink_kind: str,
) -> ArtifactManifestSourceFramesRole | Uncertified:
    """The manifest role after an exit attempt at ``sink_kind``: CONSUME/TERMINATE
    or deliberate rejection.

    Only ``MANIFEST_ADAPTER_SINK_KIND`` -- and only when ``certificate``
    actually configured the write (``writes_manifest_file``) -- may consume
    the role. Any other ``sink_kind``, or the same invocation without both
    ``manifest_path``/``output_dir`` set, is not authorized and stays
    UNCERTIFIED rather than silently granting consumption (FTR section 10:
    "current generic backends do not provide a stable cross-format
    manifest-role round trip").
    """
    if sink_kind != MANIFEST_ADAPTER_SINK_KIND or not certificate.writes_manifest_file:
        return Uncertified(reason="uncovered_configuration", detail="sink_kind")
    return ArtifactManifestSourceFramesRole(
        frame=role.frame, effect=TransitionEffect.CONSUME_TERMINATE
    )


__all__ = [
    "WRITE_ARTIFACT_MANIFEST_TARGET",
    "MANIFEST_ADAPTER_SINK_KIND",
    "ArtifactManifestCertificate",
    "classify_artifact_manifest_step",
    "artifact_manifest_role",
    "consume_manifest_at_sink",
]
