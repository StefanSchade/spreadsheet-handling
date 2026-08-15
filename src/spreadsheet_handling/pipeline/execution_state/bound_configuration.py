"""Exact bound-configuration authenticity and snapshotting for every E4 classifier.

FTR section 23 requires that certification prove *"its exact bound behavior
carries a framework-reviewed producer contract through an implementation
mechanism"* -- not a merely descriptive label. A truthful classifier answer
therefore has two independent parts, both required:

1. *Authenticity* -- was this exact ``BoundStep`` genuinely produced by a
   trusted framework binder (``pipeline/steps.py``), or could it be a
   caller-forged/hand-constructed object whose ``config`` merely *looks*
   like a certifiable invocation while ``fn`` executes something unrelated?
   ``is_trusted_binding`` answers this by checking ``step.binding is
   pipeline.types._TRUSTED_BINDING`` -- a sentinel only ``pipeline/steps.py``
   factories ever set (see that module's docstring). A step built by calling
   the public ``BoundStep(...)`` constructor directly leaves ``binding`` at
   its default of ``None`` and fails this check regardless of how
   convincing its ``config`` looks.

2. *Immutable effective configuration* (FTR section 18) -- given an
   authentically-bound step, does ``step.config`` still describe exactly
   what ``step.fn`` executes? Every ``pipeline/steps.py`` factory now
   exposes ``config`` as a read-only ``MappingProxyType`` view built from the
   *same* shallow-copied values its execution closure reads, so a caller can
   no longer reassign a top-level key after binding (that previously
   diverged the two -- see the corrected E4 review evidence); a
   ``TypeError`` is raised instead. A caller can still mutate a *nested*
   mutable value (e.g. a list under a dict key) in place, but that changes
   both the exposed config and the executing closure identically, because
   the two were never independently copied -- a real, consistently-observed
   change, not a divergence.

Every classifier in this package must therefore check authenticity *first*,
then snapshot the (now-truthfully-descriptive) configuration:

* every ``classify_*`` function re-reads ``step.config`` fresh on every
  call -- nothing about a ``BoundStep`` is cached -- so a mutation made
  *before* classification (of a nested value; top-level reassignment is no
  longer possible) is honestly reflected in the answer;
* every accepted value is immediately copied into a new, closed-type
  immutable snapshot (``str`` / ``bool`` / ``int`` / ``float`` / ``None`` /
  ``tuple[str, ...]``) before it is placed in a returned certificate, so a
  later nested mutation cannot retroactively change an already-returned
  certificate's meaning.

A configuration key outside a classifier's declared closed vocabulary, or a
value that is not one of the closed scalar/string-sequence shapes below,
yields ``None`` (unknown option / unsupported value / uncovered callback)
rather than best-effort coercion -- callers turn that into ``Uncertified``.
"""
from __future__ import annotations

from typing import Any, Mapping

from spreadsheet_handling.pipeline.types import BoundStep, _TRUSTED_BINDING


def is_trusted_binding(step: BoundStep) -> bool:
    """Whether ``step`` was genuinely produced by a trusted pipeline binder.

    This is a necessary precondition for certification, checked before any
    configuration inspection: a step failing this check is UNCERTIFIED
    regardless of how closely its ``config`` resembles a reviewed
    invocation, because its ``fn`` has no proven relationship to that
    config at all.
    """
    return step.binding is _TRUSTED_BINDING

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
    "is_trusted_binding",
    "snapshot_scalar",
    "snapshot_string_sequence",
    "only_known_keys",
]
