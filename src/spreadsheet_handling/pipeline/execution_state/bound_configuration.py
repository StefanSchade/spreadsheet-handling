"""Exact bound-configuration snapshotting shared by every E4 classifier.

FTR section 18 ("Bound configuration and mutation safety") requires a
certificate to correspond to *immutable effective configuration*.
``BoundStep`` (``pipeline/types.py``) is a frozen dataclass, but its
``config`` field is a plain mutable ``dict`` built by
``pipeline.steps.make_frames_target_step`` as
``cfg = {"target": ..., **dict(kwargs)}``. ``dict(kwargs)`` only *shallow*-
copies: a nested mutable value (e.g. a ``list`` passed as ``row_keys`` or
``helpers["fields"]``) is the *same object* that step's execution closure
(``run``, which closes over the original ``kwargs``, not ``cfg``) reads at
call time. So mutating ``bound_step.config["row_keys"]`` in place after
binding really does change what the next invocation executes -- a classifier
that just held a reference to ``step.config`` and remembered "certified"
once would be lying the moment a caller mutates that nested value.

This module solves it the smallest way that satisfies both directions of the
requirement:

* every ``classify_*`` function in this package re-reads ``step.config``
  fresh on every call -- nothing about a ``BoundStep`` is cached -- so a
  mutation made *before* classification is honestly reflected in the answer;
* every accepted value is immediately copied into a new, closed-type
  immutable snapshot (``str`` / ``bool`` / ``int`` / ``float`` / ``None`` /
  ``tuple[str, ...]``) before it is placed in a returned certificate, so a
  mutation made *after* classification cannot retroactively change an
  already-returned certificate's meaning.

A configuration key outside a classifier's declared closed vocabulary, or a
value that is not one of the closed scalar/string-sequence shapes below,
yields ``None`` (unknown option / unsupported value / uncovered callback)
rather than best-effort coercion -- callers turn that into ``Uncertified``.
"""
from __future__ import annotations

from typing import Any, Mapping

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


__all__ = ["snapshot_scalar", "snapshot_string_sequence", "only_known_keys"]
