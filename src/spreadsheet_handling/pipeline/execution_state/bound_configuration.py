"""Exact bound-configuration authenticity and snapshotting for every E4 classifier.

FTR section 23 requires that certification prove *"its exact bound behavior
carries a framework-reviewed producer contract through an implementation
mechanism"* -- not a merely descriptive label. A truthful classifier answer
therefore has two independent parts, both required:

1. *Authenticity* -- does this exact ``BoundStep`` *necessarily* execute the
   reviewed target with the configuration being inspected, or could its
   ``config``/``fn`` be an unrelated pairing that merely looks certifiable?
   ``resolve_trusted_call`` answers this structurally, not by trusting a
   caller-suppliable marker: it requires ``type(step.fn) is
   BoundFramesTargetCall`` (exact type, never ``isinstance`` -- a subclass
   could override ``__call__`` while ``target``/``kwargs`` still look
   legitimate) and ``step.fn.target is expected_target`` (object identity
   against the actual imported callable, not a string label). Because
   ``BoundFramesTargetCall.__call__`` mechanically executes
   ``self.target(frames, **thawed(self.kwargs))`` -- a fresh,
   invocation-local materialization of the same frozen ``self.kwargs``
   snapshot (see part 2 below) -- a step passing both checks *cannot*
   execute anything other than ``expected_target`` called with the exact
   configuration that snapshot describes: there is no way to construct an
   instance whose fields describe one behavior while ``__call__`` performs
   another. An
   earlier mechanism (a ``BoundStep.binding`` sentinel, ``pipeline.types
   ._TRUSTED_BINDING``) checked only *object-identity possession of an
   importable module-level value*, which any caller could import and pass
   to a hand-built ``BoundStep`` with an unrelated ``fn`` -- proven
   forgeable by the independent E4 implementation review and removed; this
   module and ``BoundFramesTargetCall`` supersede it.

2. *Immutable effective configuration* (FTR section 18) -- given an
   authentic call, does the configuration a classifier reads still describe
   exactly what executes? Classifiers read ``step.fn.kwargs`` directly, and
   ``BoundFramesTargetCall.__call__`` derives what it passes to ``target``
   from that *same authoritative frozen snapshot* -- not a same mapping
   *object*: ``__call__`` calls ``_thaw_effective_value(self.kwargs)`` to
   materialize a fresh, invocation-local ``dict``/``list`` structure (so the
   target's ordinary ``isinstance(x, dict)``-shaped call surface keeps
   working), then invokes ``self.target(frames, **materialized)``. Both the
   classifier's read and the thaw the target receives are reconstructed from
   the one frozen ``self.kwargs``, so there is no seam where they could
   describe different configurations -- but a classifier never receives the
   literal object passed to ``target``, and the reverse is also true.
   ``BoundFramesTargetCall.__post_init__`` is the sole construction path (an
   earlier ``.bind()`` path was found to be a second, bypassable
   construction route and was removed) and unconditionally *deep*-freezes
   ``kwargs`` through ``_freeze_effective_kwargs``/``_freeze_effective_value``
   in ``pipeline/types.py``, for exactly the closed shapes that vocabulary
   covers: every ``dict``/``MappingProxyType`` recursively becomes a new,
   owned ``MappingProxyType``, and every ``list``/``tuple`` becomes a new
   ``tuple``, all the way down. No caller-held reference -- top-level or
   nested -- can reassign or mutate any part of *that* frozen result after
   construction; a caller retains only its own original, now-disconnected
   container. A value outside dict/``MappingProxyType``/list/tuple/scalar
   (a DataFrame, a plugin's own object, a callback) is stored *by reference*
   and is not made immutable by this freeze -- but no E4 classifier in this
   package certifies such a shape regardless (an uncovered value yields
   ``None``/``Uncertified``, never a best-effort read), so there is nothing
   E4-relevant left unprotected.

Every classifier in this package must therefore resolve the trusted call
*first*, then snapshot the (now-provably-executed) configuration:

* every ``classify_*`` function re-reads ``step.fn``/``step.fn.kwargs``
  fresh on every call -- nothing about a ``BoundStep`` is cached -- though in
  practice no caller-held mutation of a certificate-relevant closed shape,
  top-level or nested, remains possible after ``__post_init__``'s deep
  freeze;
* every accepted value is additionally copied into a new, closed-type
  immutable snapshot (``str`` / ``bool`` / ``int`` / ``float`` / ``None`` /
  ``tuple[str, ...]``) before it is placed in a returned certificate, so a
  certificate's meaning is self-contained and does not depend on
  ``BoundFramesTargetCall.kwargs`` remaining reachable or unchanged.

A configuration key outside a classifier's declared closed vocabulary, or a
value that is not one of the closed scalar/string-sequence shapes below,
yields ``None`` (unknown option / unsupported value / uncovered callback)
rather than best-effort coercion -- callers turn that into ``Uncertified``.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from spreadsheet_handling.pipeline.types import BoundFramesTargetCall, BoundStep


def resolve_trusted_call(
    step: BoundStep, *, expected_target: Callable[..., Any]
) -> BoundFramesTargetCall | None:
    """The step's authenticated executable/config pair, or ``None``.

    Returns ``step.fn`` itself only when it is *exactly* a
    ``BoundFramesTargetCall`` (never a subclass) whose ``target`` is
    identically (``is``) ``expected_target``. Because
    ``BoundFramesTargetCall.__call__`` mechanically executes
    ``self.target(frames, **self.kwargs)``, this is a structural proof that
    ``step`` executes ``expected_target`` with exactly the configuration
    named by the returned object's ``kwargs`` -- not a caller-suppliable
    label that could describe one behavior while ``step.fn`` performs
    another. This is a necessary precondition for certification, checked
    before any configuration inspection: a step failing this check is
    UNCERTIFIED regardless of how closely its ``config`` resembles a
    reviewed invocation.
    """
    call = step.fn
    if type(call) is not BoundFramesTargetCall:
        return None
    if call.target is not expected_target:
        return None
    return call


# Exact-type membership only (``type(value) in ...``), never ``isinstance``,
# so a hostile ``__class__``-spoofing object cannot pass as a safe scalar.
# Mirrors the actual-runtime-type discipline established for E1/E2
# (``core.scalar_values`` / ``domain.ingress.structural_admission``).
_SCALAR_TYPES: tuple[type, ...] = (str, bool, int, float, type(None))


def snapshot_scalar(value: Any) -> Any:
    """Return ``value`` unchanged if it is an exact closed-set immutable scalar.

    Otherwise return ``None``, marking it unsupported/uncovered. Note ``None``
    is itself a valid closed-set scalar (an absent option); callers that need
    to distinguish "absent" from "unsupported" check the source key's
    presence separately.
    """
    if type(value) in _SCALAR_TYPES:
        return value
    return None


def snapshot_string_sequence(value: Any) -> tuple[str, ...] | None:
    """Freeze a ``str`` or ``list``/``tuple`` of ``str`` into an owned tuple.

    Every element's *actual* type must be exactly ``str``; anything else
    (a ``str`` subclass, a generator, a nested collection) yields ``None``.
    """
    if type(value) is str:
        return (value,)
    if type(value) is list or type(value) is tuple:
        items: list[str] = []
        for item in value:
            if type(item) is not str:
                return None
            items.append(item)
        return tuple(items)
    return None


def only_known_keys(config: Mapping[str, Any], *, known: frozenset[str]) -> bool:
    """Whether every key of ``config`` is in the classifier's declared vocabulary.

    A key outside ``known`` means the bound invocation used an option this
    classifier has not reviewed; the caller must treat that as UNCERTIFIED
    rather than silently ignoring it (FTR section 4: "Unknown/uncovered
    configuration MUST result in UNCERTIFIED, not close enough").
    """
    return set(config.keys()) <= known


__all__ = [
    "resolve_trusted_call",
    "snapshot_scalar",
    "snapshot_string_sequence",
    "only_known_keys",
]
