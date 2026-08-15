"""Canonical pipeline type definitions.

All pipeline-related types live here to avoid circular imports.
Other modules (steps, registry, runner) import from this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
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


def _freeze_effective_value(value: Any) -> Any:
    """Recursively freeze ``value`` into an immutable equivalent.

    Used to build a ``BoundFramesTargetCall``'s stored ``kwargs`` so that no
    alias the *caller* still holds to the original mutable containers it
    passed in (a ``dict``, a nested ``list``) can affect that call's
    executable behavior after construction -- FTR-TRUSTED-INGRESS-P4A
    section 18's "certificate corresponds to immutable effective
    configuration" requirement, applied to the object itself, not only to
    one ``MappingProxyType`` view of it.

    ``dict`` -> ``MappingProxyType`` wrapping a *new* dict of recursively
    frozen values (never the caller's own dict, so later mutating the
    original has no effect). ``list``/``tuple`` -> a *new* ``tuple`` of
    recursively frozen values (a tuple is re-frozen too, in case it holds a
    mutable nested element). Any other value -- an already-immutable scalar,
    or a shape outside this closed vocabulary (e.g. a DataFrame, a plugin's
    own object, a callback) -- is returned by reference: this is a generic
    binder used by many non-E4-reviewed targets too, and any value shape
    outside dict/list/tuple/scalar is never accepted by an E4 classifier
    regardless (see ``pipeline.execution_state.bound_configuration``), so
    there is nothing E4-relevant to protect for it, and copying it would
    only risk changing identity-sensitive non-E4 behavior for no benefit.
    """
    if type(value) is dict:
        return MappingProxyType(
            {key: _freeze_effective_value(item) for key, item in value.items()}
        )
    if type(value) is list or type(value) is tuple:
        return tuple(_freeze_effective_value(item) for item in value)
    return value


def _thaw_effective_value(value: Any) -> Any:
    """Invert :func:`_freeze_effective_value` for exactly one invocation.

    Materializes fresh, invocation-local ``dict``/``list`` containers from a
    frozen snapshot, so a reviewed target's ordinary ``dict``/``list``-shaped
    call surface (e.g. ``isinstance(helpers, dict)``) keeps working exactly
    as before freezing was introduced. The frozen snapshot itself is never
    mutated by this: every call produces new containers, and a later
    invocation of the same ``BoundFramesTargetCall`` materializes fresh ones
    from that same unchanged snapshot again.
    """
    if type(value) is MappingProxyType:
        return {key: _thaw_effective_value(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_effective_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class BoundFramesTargetCall:
    """The closed executable/configuration pair for a frames-first target
    callable (``target(frames, **kwargs) -> Frames | None``).

    This is the *only* way ``pipeline.steps.make_frames_target_step`` builds
    a ``BoundStep.fn``: ``__call__`` mechanically invokes exactly
    ``self.target(frames, **thawed(self.kwargs))``. There is therefore no
    way to construct an instance whose declared ``target``/``kwargs``
    describe one behavior while ``__call__`` performs another -- inspecting
    the fields *is* inspecting what executes, not a separately maintained
    description of it that could drift or be forged independently of the
    callable that actually runs.

    This is the structural authenticity proof Phase-E Trusted Ingress E4
    certification relies on (see
    ``pipeline.execution_state.bound_configuration.resolve_trusted_call``):
    a classifier that confirms ``type(step.fn) is BoundFramesTargetCall``
    (never ``isinstance`` -- a subclass could override ``__call__`` while
    ``target``/``kwargs`` still look legitimate) and ``step.fn.target is
    <the exact reviewed callable>`` (object identity, not a string label a
    caller could supply independently of what actually runs) has proven the
    executed behavior. Two earlier mechanisms were each found insufficient
    and are superseded by this class; nothing in this codebase still
    references either:

    * a sentinel-marker (``BoundStep.binding``) -- possessing an importable
      module-level value proved nothing about what a hand-constructed
      step's ``fn`` does;
    * an *unfrozen* version of this same class -- ``target``/``kwargs`` were
      ordinary reassignable attributes, so ``call.target = malicious`` or
      ``call.kwargs = other_mapping`` silently changed what an
      already-certified, genuinely framework-built call executed while its
      already-issued certificate stayed unchanged (independent E4
      implementation review `01c2e93`, section 17.3).

    ``@dataclass(frozen=True, slots=True)`` makes ordinary attribute
    reassignment raise ``FrozenInstanceError`` for *both* fields -- real
    enforced immutability, not a naming convention. ``kwargs`` is stored
    already deep-frozen via :func:`_freeze_effective_value` (see
    :meth:`bind`), not merely wrapped in one top-level
    ``types.MappingProxyType``: a caller mutating the *original* dict/list it
    passed in after binding cannot affect this call's stored configuration,
    because the stored structures share no mutable object with anything the
    caller still holds. Classifiers read ``self.kwargs`` directly (the exact
    frozen structure ``__call__`` also reads, via
    :func:`_thaw_effective_value`), so there is no separate "classifier
    snapshot" that could itself drift from what executes.
    """

    target: Callable[..., Any]
    kwargs: Mapping[str, Any]

    @classmethod
    def bind(cls, target: Callable[..., Any], kwargs: Mapping[str, Any]) -> BoundFramesTargetCall:
        """Construct a call with ``kwargs`` deep-frozen (see
        :func:`_freeze_effective_value`). The only supported construction
        path for a genuinely bound call; this is what
        ``pipeline.steps.make_frames_target_step`` uses.
        """
        return cls(target, _freeze_effective_value(kwargs))

    def __call__(self, frames: Frames) -> Frames:
        materialized = _thaw_effective_value(self.kwargs)
        result = self.target(frames, **materialized)
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
