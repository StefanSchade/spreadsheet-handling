"""Shared E4 vocabulary: transition effects and bounded transition footprints.

Phase-E slice E4 (``docs/backlog/FTR-TRUSTED-INGRESS-P4A.adoc`` section 23,
"exact producer-transition representation and bounded certificates") needs a
small, closed vocabulary that every role-specific descriptor in this package
reuses, so a fresh maintainer reads one place to learn the effect words
instead of re-deriving them per role. This is deliberately *not* a generic
effect system: there is no execution engine here, only named values a caller
(currently tests; E5 later) can construct and compare. Nothing in this
package threads through the orchestrator, ``run_pipeline``, or any
public/YAML-addressable surface -- see the FTR's E4 scope exclusions.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class TransitionEffect(Enum):
    """The accepted effect vocabulary (FTR section 8), named exactly.

    ``INTRODUCE``
        A role appears where none existed before.
    ``COPY_DERIVE``
        The source role remains live; another authorized occurrence is
        established.
    ``RELOCATE``
        Authorization moves; the old location no longer carries the role.
    ``CONSUME_TERMINATE``
        Role authority ends.
    ``PENDING_CLEANUP``
        The role remains present and authorized in the published state until
        a later exact cleanup transition removes its location.

    The FTR is explicit that these must not collapse into a generic boolean
    such as ``preserves_role = True``; every role-transition function in this
    package returns a value carrying one of these five effects rather than a
    yes/no answer.
    """

    INTRODUCE = "introduce"
    COPY_DERIVE = "copy_derive"
    RELOCATE = "relocate"
    CONSUME_TERMINATE = "consume_terminate"
    PENDING_CLEANUP = "pending_cleanup"


UncertifiedReason = Literal[
    "unauthenticated_binding",
    "unrecognized_target",
    "unknown_option",
    "unsupported_configuration_value",
    "uncovered_configuration",
    "uncovered_callback",
    "mismatched_composition",
    "locality_collision",
]


@dataclass(frozen=True)
class Uncertified:
    """The closed default outcome for a bound invocation or a proposed role product.

    Carries only a stable ``reason`` code and a short, caller-safe ``detail``
    string naming *which option/location* failed -- never the rejected value
    itself. This matches the classify-before-inspect diagnostic discipline
    already established for E1/E2 (``OrdinaryScalarAdmissionError`` /
    ``OrdinaryStructureAdmissionError``): a candidate that reaches this
    package has *not* been proven safe to ``repr()``/``str()``, so no
    classifier here does that.
    """

    reason: UncertifiedReason
    detail: str = ""


@dataclass(frozen=True)
class TransitionFootprint:
    """The exact top-level Frames keys one certified transition touches.

    Used only for the bounded disjoint-role-product proof (FTR section 10,
    "Controlled-role composition decision"): a later transition preserves an
    already-live role only when its footprint provably does not intersect
    that role's location. Every field is the transition's *own declared*
    frame names, taken directly from its exact bound configuration -- never
    observed runtime behaviour -- so the proof is semantic (the transition's
    contract), not "our test did not mutate it" or "same object still
    exists".
    """

    reads: frozenset[str]
    writes: frozenset[str]
    drops: frozenset[str]

    def touches(self, frame: str) -> bool:
        return frame in self.reads or frame in self.writes or frame in self.drops


def proves_disjoint(footprint: TransitionFootprint, *, existing_role_frame: str) -> bool:
    """Whether ``footprint`` provably cannot affect a role at ``existing_role_frame``.

    Role identity, payload, descriptor/provenance, and relocation identity for
    every bounded role kind in this package live entirely in the Frames
    top-level entry named by its own ``frame`` field -- none of the
    maintained role kinds stashes state in ``_meta`` or another frame's cells
    (FTR section 10: "The GroupedHeader is carrier-owned structure, not
    ``_meta``"). Frame-name non-intersection is therefore a *sufficient*
    proof for this bounded role set, not merely a necessary one.
    """
    return not footprint.touches(existing_role_frame)


__all__ = [
    "TransitionEffect",
    "UncertifiedReason",
    "Uncertified",
    "TransitionFootprint",
    "proves_disjoint",
]
