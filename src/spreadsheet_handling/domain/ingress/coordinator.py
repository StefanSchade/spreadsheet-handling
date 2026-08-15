"""Carrier-neutral domain ingress coordinator.

Ingress is a framework-owned macro-flow transformation that canonicalizes
externally authored ``_meta`` the moment it enters the domain, so every
downstream consumer observes one canonical shape. It is deliberately *not* a
user-configurable pipeline step: it is absent from ``pipeline.registry.REGISTRY``
and ``registries/pipeline_step_registry.json``, cannot be built from YAML, and
is invoked automatically by the orchestrator and by the two maintained
configuration-to-meta merges (``bootstrap_meta``, ``apply_overrides``).

The coordinator is a deterministic ``Frames -> Frames`` transformation. It
applies an *ordered, visible* sequence of feature-owned rules (``INGRESS_RULES``)
so later ingress normalizations can be added here without hiding unrelated
logic inside orchestration. Each rule is pure and non-mutating; because no rule
mutates the caller's object graph, a failure in any rule leaves the input
frames, ``_meta``, and nested metadata unchanged and aborts before any later
rule, configured step, or persistence runs.

``ordinary_structural_admission`` (Phase-E slice E2, which itself validates
every ordinary cell through slice E1) runs first: it is the base ordinary
carrier/Scalar check every later rule's authored-shape assumptions build on,
and it deliberately leaves the reserved ``_meta`` entry unopened so slice E3's
delegate/substrate rules keep sole ownership of metadata content (FTR-TRUSTED-
INGRESS-P4A section 6: "ordinary Scalar cells, accepted structural carriers,
accepted metadata substrate", in that order). Phase-E slice E5
(``docs/backlog/FTR-TRUSTED-INGRESS-P4A.adoc`` section 23, "framework-managed
macro wiring") is what wires this rule into the coordinator; the rule itself
(``domain.ingress.structural_admission.admit_ordinary_frames``) was
implemented and independently accepted under slice E2 without being wired
here -- see that module's docstring.

This package establishes the ``domain.ingress`` vocabulary. Its documented
symmetric counterpart, ``domain.egress`` (framework-owned projection/pruning
when Frames leave the domain), is reserved as a future concept only; this slice
does not build a generic egress engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .legend_blocks import normalize_legend_blocks_shape
from .metadata_admission import admit_metadata_substrate
from .structural_admission import admit_ordinary_frames

Frames = dict[str, Any]


@dataclass(frozen=True)
class IngressRule:
    """One named, feature-owned ``Frames -> Frames`` ingress normalization."""

    name: str
    apply: Callable[[Frames], Frames]


# Ordered rule sequence. Kept explicit and module-level so the ingress
# contract is discoverable and extensible: append a new IngressRule here rather
# than threading ad-hoc normalization through the orchestrator.
#
# ``ordinary_structural_admission`` runs first (E2/E1): it establishes the
# base ordinary carrier/cell facts every later rule assumes and never opens
# ``_meta``, so its position relative to the ``_meta``-only rules below is a
# documentation choice (FTR section 6 ordering), not a functional dependency.
#
# ``metadata_substrate`` runs last and deliberately after every authoring-shape
# delegate (currently only ``legend_blocks_shape``): it validates the
# *complete* post-delegate ``_meta`` tree against the Phase-E E3 bounded
# substrate grammar, so a delegate's own output is checked by the same generic
# recursive pass as directly authored metadata -- no delegate output is exempt
# by virtue of delegate status. See ``metadata_admission.py``.
INGRESS_RULES: tuple[IngressRule, ...] = (
    IngressRule(name="ordinary_structural_admission", apply=admit_ordinary_frames),
    IngressRule(name="legend_blocks_shape", apply=normalize_legend_blocks_shape),
    IngressRule(name="metadata_substrate", apply=admit_metadata_substrate),
)


def run_domain_ingress(frames: Frames) -> Frames:
    """Apply the ordered ingress rule sequence and return canonical Frames.

    Pure and non-mutating: on success the caller's ``frames`` is returned
    unchanged when no rule applies, otherwise a new frames dict with canonical
    ``_meta`` is returned. On any rule failure the input object graph is
    unchanged and the exception propagates before persistence.
    """
    result = frames
    for rule in INGRESS_RULES:
        result = rule.apply(result)
    return result


__all__ = ["IngressRule", "INGRESS_RULES", "run_domain_ingress"]
