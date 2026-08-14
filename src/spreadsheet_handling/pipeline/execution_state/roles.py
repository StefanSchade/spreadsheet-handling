"""The closed controlled-role descriptors (FTR sections 6, 7, and 10).

Exactly three role kinds are maintained, plus the one admitted nested
composition:

* ``LookupFormulaSpecRole`` -- standalone ``FormulaSpec`` helper-cell role.
* ``GroupedMatrixRole`` -- top-level structural carrier role.
* ``GroupedMatrixFormulaRole`` -- the one admitted nesting,
  ``GroupedMatrix[LookupFormulaSpec@grouped-dynamic-value-cell-role]``.
* ``ArtifactManifestSourceFramesRole`` -- the exact manifest
  ``source_frames`` role.

``DeclaredComposite`` stays empty; no other role kind is represented (FTR
section 6, "Closed controlled-role set"). Each descriptor names only the
facts its own kind's contract requires -- there is no shared generic schema
across kinds because the roles are not shaped alike (FTR section 7, "Role
descriptors must be semantic, not nominal").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Union

from .vocabulary import TransitionEffect


@dataclass(frozen=True)
class LookupFormulaSpecRole:
    """A standalone ``LookupFormulaSpec`` occurrence at one exact cell location.

    One descriptor per column: ``add_lookup_helpers(helper_value_mode="formula")``
    creates one ``LookupFormulaSpec`` per requested field, each with its own
    ``lookup_value_column`` (FTR section 9, "Standalone FormulaSpec
    transition"), so this descriptor deliberately covers exactly one column
    rather than a list of columns sharing one provenance record.

    ``pending_cleanup`` names the FTR's PENDING CLEANUP state (section 8):
    the role remains live and authorized at ``frame``/``column`` until a
    later exact final-cleanup transition removes that whole frame.
    """

    frame: str
    column: str
    source_key_column: str
    lookup_sheet: str
    lookup_key_column: str
    missing: str
    effect: TransitionEffect
    pending_cleanup: bool = False


@dataclass(frozen=True)
class GroupedMatrixRole:
    """A standalone (ordinary-valued) ``GroupedMatrix`` carrier role.

    ``producer`` names the exact reviewed introducing transition (FTR section
    10, "GroupedMatrix lifecycle decision", Option G1: transition-only
    internal carrier). ``source`` is the frame that supplied its contents
    (``relation`` for ``contract_grouped_xref``, the input ``ExactTable``
    frame for ``reconstruct_grouped_matrix``) and is retained only for
    footprint/locality bookkeeping -- geometry, bijection, and reconstruction
    semantics stay family-owned (FTR section 26).
    """

    frame: str
    producer: str
    source: str
    effect: TransitionEffect


@dataclass(frozen=True)
class GroupedMatrixFormulaRole:
    """The one admitted nested composition (FTR section 10,
    "FormulaSpec-in-GroupedMatrix composition descriptor").

    Every dynamic (non-row-key) cell of ``frame`` derived from ``source``'s
    selected column carries ``LookupFormulaSpec`` authority; every other
    contained cell stays ordinary Scalar (family-owned, not re-proved here).
    ``source`` is the exact retained standalone role this nesting was
    derived from, so its full provenance (source/lookup keys, lookup sheet,
    missing policy) survives into any later relocation/derivation without
    re-deriving it.
    """

    frame: str
    source: LookupFormulaSpecRole
    effect: TransitionEffect


@dataclass(frozen=True)
class ArtifactManifestSourceFramesRole:
    """The exact manifest ``source_frames`` role (FTR section 10,
    "Artifact-manifest role decision", Option M1).

    Always column ``"source_frames"`` of the manifest producer's declared
    ``output`` frame; every value is a freshly owned one-level ``list[str]``.
    """

    frame: str
    effect: TransitionEffect = TransitionEffect.INTRODUCE
    column: str = "source_frames"


ControlledRole = Union[
    LookupFormulaSpecRole,
    GroupedMatrixRole,
    GroupedMatrixFormulaRole,
    ArtifactManifestSourceFramesRole,
]


def terminate_roles_removed_by_cleanup(
    roles: Iterable[ControlledRole],
    *,
    removed_frames: frozenset[str],
) -> tuple[ControlledRole, ...]:
    """FTR section 8, CONSUME/TERMINATE at final cleanup.

    Final cleanup terminates only the roles located exclusively in a removed
    whole frame; every other role remains at its declared location
    unchanged. This is a pure set-difference over declared ``frame`` values,
    not a re-implementation of ``execute_final_domain_cleanup`` -- cleanup
    resolution (which frames are actually removed) stays orchestrator-owned.
    """
    return tuple(role for role in roles if role.frame not in removed_frames)


__all__ = [
    "LookupFormulaSpecRole",
    "GroupedMatrixRole",
    "GroupedMatrixFormulaRole",
    "ArtifactManifestSourceFramesRole",
    "ControlledRole",
    "terminate_roles_removed_by_cleanup",
]
