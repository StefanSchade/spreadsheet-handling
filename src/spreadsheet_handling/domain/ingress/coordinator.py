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

This package establishes the ``domain.ingress`` vocabulary. Its documented
symmetric counterpart, ``domain.egress`` (framework-owned projection/pruning
when Frames leave the domain), is reserved as a future concept only; this slice
does not build a generic egress engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .legend_blocks import normalize_legend_blocks_shape

Frames = dict[str, Any]


@dataclass(frozen=True)
class IngressRule:
    """One named, feature-owned ``Frames -> Frames`` ingress normalization."""

    name: str
    apply: Callable[[Frames], Frames]


# Ordered rule sequence. Kept explicit and module-level so the ingress
# contract is discoverable and extensible: append a new IngressRule here rather
# than threading ad-hoc normalization through the orchestrator.
INGRESS_RULES: tuple[IngressRule, ...] = (
    IngressRule(name="legend_blocks_shape", apply=normalize_legend_blocks_shape),
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
