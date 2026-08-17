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

    ``dict``/``MappingProxyType`` -> a *new*, owned ``MappingProxyType``
    wrapping a *new* dict of recursively frozen values -- never the
    caller's own dict, and never merely re-wrapping a ``MappingProxyType``
    that could still be backed by a live caller-owned dict (a
    ``MappingProxyType`` is a *view*, not a copy: freezing it means reading
    its *current* key/value pairs into a disconnected structure, exactly as
    for a plain ``dict``). ``list``/``tuple`` -> a *new* ``tuple`` of
    recursively frozen values (a tuple is re-frozen too, in case it holds a
    mutable nested element). Any other value -- an already-immutable
    scalar, or a shape outside this closed vocabulary (e.g. a DataFrame, a
    plugin's own object, a callback) -- is returned by reference: this is a
    generic binder used by many targets too. A controlled-role classifier
    must fail closed when such a by-reference leaf can affect semantics on
    which its certificate relies (see
    ``pipeline.execution_state.bound_configuration``); the binder itself does
    not claim arbitrary-object immutability. Copying opaque leaves here would
    risk changing identity-sensitive trusted-programmatic behavior.
    """
    if type(value) is dict or type(value) is MappingProxyType:
        return MappingProxyType(
            {key: _freeze_effective_value(item) for key, item in value.items()}
        )
    if type(value) is list or type(value) is tuple:
        return tuple(_freeze_effective_value(item) for item in value)
    return value


def _freeze_effective_kwargs(kwargs: Mapping[str, Any]) -> Mapping[str, Any]:
    """The one root-level canonicalization every ``BoundFramesTargetCall``
    construction funnels through (see ``__post_init__``).

    Accepts only an exact built-in ``dict`` or an exact ``MappingProxyType``
    at this boundary -- every current framework binding path
    (``pipeline.steps.make_frames_target_step``) starts from ordinary
    ``**kwargs``, and E4 needs one closed, authoritative configuration
    representation, not an open set of caller-suppliable ``Mapping``
    implementations whose own ``__getitem__``/``keys()`` could do anything.
    Any other ``Mapping`` (or non-mapping) is rejected with ``TypeError``:
    no current maintained construction path supplies one, and this is the
    exact construction boundary the whole immutability invariant depends
    on, so it fails closed rather than silently trusting an unrecognized
    shape.
    """
    if type(kwargs) is not dict and type(kwargs) is not MappingProxyType:
        raise TypeError(
            "BoundFramesTargetCall kwargs must be an exact dict or "
            f"MappingProxyType, got {type(kwargs).__name__}"
        )
    return _freeze_effective_value(kwargs)


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
    executed behavior. Three earlier mechanisms were each found insufficient
    and are superseded by this class; nothing in this codebase still
    references any of them:

    * a sentinel-marker (``BoundStep.binding``) -- possessing an importable
      module-level value proved nothing about what a hand-constructed
      step's ``fn`` does;
    * an *unfrozen* version of this same class -- ``target``/``kwargs`` were
      ordinary reassignable attributes, so ``call.target = malicious`` or
      ``call.kwargs = other_mapping`` silently changed what an
      already-certified, genuinely framework-built call executed while its
      already-issued certificate stayed unchanged (independent E4
      implementation review `01c2e93`, section 17.3);
    * a frozen version that only deep-froze ``kwargs`` inside a *separate*
      ``bind()`` classmethod -- the public, dataclass-generated
      ``BoundFramesTargetCall(target, kwargs)`` constructor remained a
      second, unfrozen construction path that ``resolve_trusted_call``
      accepted identically, so a caller-held mutable ``kwargs`` dict (or a
      nested alias inside it, or a ``MappingProxyType`` wrapping a still-live
      dict) passed directly to that constructor could still be mutated
      after certification (independent E4 implementation review `9feb324`,
      section 18.4).

    The invariant this class now owns is: **every object
    ``resolve_trusted_call`` can accept has one authoritative effective
    binding snapshot from the instant construction completes** -- not merely
    the subset built through one particular classmethod. Its supported
    container structure is immutable; arbitrary leaves may remain by
    reference for trusted-programmatic compatibility and therefore require a
    separate fail-closed classifier check before controlled-role authority.
    ``@dataclass(frozen=True, slots=True)`` makes ordinary attribute
    reassignment raise ``FrozenInstanceError`` for both fields, and
    ``__post_init__`` unconditionally replaces whatever ``kwargs`` object
    the constructor was given with :func:`_freeze_effective_kwargs`'s
    canonical, deep-frozen result -- there is no supported constructor
    argument, keyword, or classmethod that skips this. A caller mutating
    the *original* dict/list/``MappingProxyType`` it passed in after
    construction cannot affect this call's stored container structure,
    because those containers are rebuilt without caller-held aliases.
    Opaque leaves outside the freeze vocabulary may still be shared; a
    certificate may depend on them only if its classifier represents them in
    a closed stable contract, and otherwise must return ``Uncertified``.
    Classifiers read ``self.kwargs`` directly (the authoritative frozen
    structure ``__call__`` also reads, via :func:`_thaw_effective_value`), so
    there is no separate "classifier snapshot" that could itself drift from
    what executes.

    Normal-construction threat boundary: this invariant covers ordinary
    Python construction, attribute assignment, and container mutation
    reachable through this class's own public surface -- including direct
    ``BoundFramesTargetCall(target, kwargs)`` construction, caller-held
    aliases, subclassing, and copying/reusing an instance. It does not
    defend against ``object.__new__`` bypassing ``__init__``, deliberate
    ``object.__setattr__`` abuse of the frozen-dataclass protection,
    ``function.__code__`` patching, ``ctypes``/memory manipulation, or
    interpreter compromise -- E4 is an exact execution-contract mechanism
    inside an already-trusted runtime (the FTR's trusted-description
    precondition), not a Python sandbox, and defending against a caller
    already willing to use those mechanisms is out of Phase-E's scope.
    """

    target: Callable[..., Any]
    kwargs: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "kwargs", _freeze_effective_kwargs(self.kwargs))

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
