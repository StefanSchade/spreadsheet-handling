"""Canonical pipeline type definitions.

All pipeline-related types live here to avoid circular imports.
Other modules (steps, registry, runner) import from this module.
"""
from __future__ import annotations

from dataclasses import dataclass
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


class BoundFramesTargetCall:
    """The closed executable/configuration pair for a frames-first target
    callable (``target(frames, **kwargs) -> Frames | None``).

    This is the *only* way ``pipeline.steps.make_frames_target_step`` builds
    a ``BoundStep.fn``: ``__call__`` mechanically invokes exactly
    ``self.target(frames, **self.kwargs)``. There is therefore no way to
    construct an instance whose declared ``target``/``kwargs`` describe one
    behavior while ``__call__`` performs another -- inspecting the fields
    *is* inspecting what executes, not a separately maintained description
    of it that could drift or be forged independently of the callable that
    actually runs.

    This is the structural authenticity proof Phase-E Trusted Ingress E4
    certification relies on (see
    ``pipeline.execution_state.bound_configuration.resolve_trusted_call``):
    a classifier that confirms ``type(step.fn) is BoundFramesTargetCall``
    (never ``isinstance`` -- a subclass could override ``__call__`` while
    ``target``/``kwargs`` still look legitimate) and ``step.fn.target is
    <the exact reviewed callable>`` (object identity, not a string label a
    caller could supply independently of what actually runs) has proven the
    executed behavior. A prior sentinel-marker mechanism
    (``BoundStep.binding``) was found forgeable -- possessing an importable
    module-level value proves nothing about what a hand-constructed step's
    ``fn`` does -- and is superseded by this class; nothing in this codebase
    still references it.

    ``kwargs`` should be an immutable mapping (the binder wraps it in
    ``types.MappingProxyType``) so a caller cannot reassign a top-level key
    after binding; a nested mutable value remains mutable in place and
    changes both this object's own view and ``BoundStep.config`` (built from
    the same underlying values) identically -- a real, consistently observed
    change, not a divergence.
    """

    __slots__ = ("target", "kwargs")

    def __init__(self, target: Callable[..., Any], kwargs: Mapping[str, Any]) -> None:
        self.target = target
        self.kwargs = kwargs

    def __call__(self, frames: Frames) -> Frames:
        result = self.target(frames, **self.kwargs)
        return frames if result is None else result


@dataclass(frozen=True)
class BoundStep:
    """
    Bound step (Name + Config + Callable).
    name/config are useful for logging, debugging, and introspection.
    fn encapsulates the actual logic (typically a closure from a factory, or
    a ``BoundFramesTargetCall`` for steps built by
    ``pipeline.steps.make_frames_target_step``).
    """
    name: str
    config: Mapping[str, Any]
    fn: Callable[[Frames], Frames]

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
