"""Canonical pipeline type definitions.

All pipeline-related types live here to avoid circular imports.
Other modules (steps, registry, runner) import from this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Protocol, TypedDict

import pandas as pd

# ---------------------------------------------------------------------------
# Core payload type
# ---------------------------------------------------------------------------

Frames = Dict[str, pd.DataFrame]


# ---------------------------------------------------------------------------
# Step protocol & bound step
# ---------------------------------------------------------------------------

class Step(Protocol):
    """A step transforms a map of frames into another map of frames."""
    name: str
    config: Dict[str, Any]

    def __call__(self, frames: Frames) -> Frames: ...


class _TrustedBinding:
    """Framework-owned marker proving a ``BoundStep`` was produced by a
    trusted binder factory in ``pipeline/steps.py``, not hand-constructed.

    Every factory in ``pipeline/steps.py`` passes the shared module-level
    ``_TRUSTED_BINDING`` instance as ``BoundStep.binding`` when it builds a
    step. Nothing outside this module constructs a ``_TrustedBinding``
    instance, so a ``BoundStep`` built directly by calling the public
    ``BoundStep(...)`` constructor (a forged or caller-supplied step) leaves
    ``binding`` at its default of ``None`` and cannot present a matching
    token merely by supplying a public-looking ``config`` dict. This is the
    authenticity half of Phase-E Trusted Ingress E4's exact-bound
    certification (FTR-TRUSTED-INGRESS-P4A section 23): a classifier proves
    both "this exact configuration" *and* "this step was genuinely produced
    by binding that configuration to its matching callable," not either
    alone. See ``pipeline.execution_state.bound_configuration.is_trusted_binding``.
    """

    __slots__ = ()


_TRUSTED_BINDING = _TrustedBinding()


@dataclass(frozen=True)
class BoundStep:
    """
    Bound step (Name + Config + Callable).
    name/config are useful for logging, debugging, and introspection.
    fn encapsulates the actual logic (typically a closure from a factory).

    ``binding`` defaults to ``None`` for any step built by directly calling
    this constructor. Every factory in ``pipeline/steps.py`` instead passes
    the shared ``_TRUSTED_BINDING`` sentinel and builds ``config`` as a
    read-only view over the exact same mapping its execution closure reads,
    so ``config`` and executable behavior cannot diverge for a trusted-bound
    step (see ``pipeline/steps.py`` module docstring and FTR section 18).
    """
    name: str
    config: Mapping[str, Any]
    fn: Callable[[Frames], Frames]
    binding: object = field(default=None, repr=False)

    def __call__(self, frames: Frames) -> Frames:
        return self.fn(frames)


StepFactory = Callable[..., BoundStep]
StepTarget = str | Callable[..., Any]


@dataclass(frozen=True)
class StepRegistration:
    """
    Normalized registry entry for pipeline-addressable steps.

    factory remains the extension point for how a step is bound.
    target optionally identifies the underlying domain callable when a generic
    binding path is used.
    """
    factory: StepFactory
    target: StepTarget | None = None


# ---------------------------------------------------------------------------
# Step specification (for config binding)
# ---------------------------------------------------------------------------

class StepSpec(TypedDict, total=False):
    step: str
    name: str
    defaults: Dict[str, Any]
    mode_missing_fk: str
    mode_duplicate_ids: str
    prefix: str
    # plugin-specific
    dotted: str
    args: Dict[str, Any]
