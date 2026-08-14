"""Metadata substrate admission for the Trusted Ingress boundary (Phase-E E3).

This module owns Phase-E slice E3: after ``_meta`` has passed any earlier
ingress rule (e.g. ``legend_blocks_shape``'s authoring-shape normalization), it
validates the *complete* ``_meta`` tree against the accepted bounded metadata
substrate grammar (`FTR-TRUSTED-INGRESS-P4A` section 11, corrected and
finalized by the accepted `FTR-TRUSTED-INGRESS-P4A_E3_metadata_census.adoc`
sections 17.4/18.9/19.10/20.7):

    _meta root:                 exact ``dict``
    recursive ordinary containers: exact ``dict``, exact ``list``
    ordinary dict keys:         exact ``str``, zero exceptions
    ordinary leaves:            E1-admitted ordinary Scalar
    aliases:                    shared acyclic aliases permitted
    cycles:                     rejected
    delegate output:            subject to this same recursive check

Why exact built-ins, not ``isinstance``: a ``dict``/``list`` subclass, a
``Mapping``/``Sequence`` implementation, or an opaque object that merely
supports iteration is not admitted merely because Python can traverse it
(`docs/backlog/FTR-TRUSTED-INGRESS-P4A.adoc` section 3 of the implementation
brief). Exact-type dispatch (``type(x) is dict``) also cannot be spoofed by an
instance-level ``__class__`` override, unlike ``isinstance``.

Why aliases are allowed but cycles are not: the accepted census (section 17.5)
distinguishes framework *ownership/validation* authority from *unique Python
object identity*. A shared child reachable from two independent, already
-completed paths is an ordinary acyclic DAG shape and is common in authored
metadata (e.g. two Legend Blocks entries pointing at the same shared style
mapping); rejecting it would be a false positive. A cycle -- reaching a
container that is still an *active ancestor* of the current traversal path --
would make traversal non-terminating and has no legitimate authoring use.
Detection is therefore path-active (a stack of ``id()``s currently being
visited), never a global "seen once" set, which would incorrectly reject
aliases.

Why delegate output is post-checked here rather than trusted: a named ingress
delegate (e.g. Legend Blocks) owns authoring-shape normalization for its own
root, not the global structural grammar. Its complete output is ordinary
``_meta`` content by the time this rule runs (delegates run as earlier
``INGRESS_RULES`` entries), so the single recursive walk below covers it
without a separate delegate-output pass -- an out-of-grammar node produced by
a delegate cannot escape by virtue of delegate status.

Why no generic coercion: `set`, `bytes`, `tuple`, `complex`, and non-``str``
dict keys are carrier-reachable (legacy XLSX/ODS Python-literal metadata,
YAML ``!!set``/``!!binary`` sidecar tags) but have no maintained family
semantic contract (census sections 17.1-17.3, 18.1-18.6). Converting them
(``str()``, ``list()``, ...) would silently change meaning; this module
rejects them deterministically instead, with a safe structural diagnostic. No
node is silently stringified or reinterpreted -- rejection composes uniformly
whether the unsupported node came from a fresh authoring source or a legacy
carrier, since this module is deliberately carrier-agnostic.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

from .scalar_admission import OrdinaryScalarAdmissionError, admit_ordinary_scalar

Frames = dict[str, Any]

_FailureKind = Literal[
    "invalid_metadata_root",
    "unsupported_metadata_key",
    "invalid_metadata_node",
    "metadata_cycle_detected",
]

# A path segment is one of:
#   ("key", <validated str key>)      -- safe to render verbatim
#   ("index", <int list index>)       -- always safe, always known
#   ("entry", <int dict-entry ordinal>) -- key itself failed validation;
#                                          named only by position, per the
#                                          census's diagnostic-safety rule
#                                          (section 18.7): never repr/str the
#                                          rejected key.
_PathSegment = tuple[str, "str | int"]


class MetadataSubstrateAdmissionError(TypeError):
    """A safe, positional E3 rejection with no rejected value ever rendered.

    ``metadata_path`` is composed only from already-admitted ``str`` keys and
    list ordinals (plus, for an unsupported key, its parent path and entry
    ordinal -- never the key itself). No rejection path in this module calls
    ``repr``, ``str``, equality, hashing, or iteration on the candidate that
    caused the failure; scalar-leaf classification is fully delegated to E1's
    already-safe ``admit_ordinary_scalar``.
    """

    def __init__(
        self,
        *,
        kind: _FailureKind,
        metadata_path: str,
        expected_node_kind: str | None = None,
        carrier_type_name: str | None = None,
    ) -> None:
        self.kind = kind
        self.metadata_path = metadata_path
        self.expected_node_kind = expected_node_kind
        self.carrier_type_name = carrier_type_name
        super().__init__(
            _safe_admission_message(
                kind=kind,
                metadata_path=metadata_path,
                expected_node_kind=expected_node_kind,
                carrier_type_name=carrier_type_name,
            )
        )


def _safe_admission_message(
    *,
    kind: _FailureKind,
    metadata_path: str,
    expected_node_kind: str | None,
    carrier_type_name: str | None,
) -> str:
    if kind == "metadata_cycle_detected":
        return (
            f"metadata substrate admission failed ({kind}) at {metadata_path}: "
            "already active on the current ancestor path"
        )
    if kind == "invalid_metadata_node":
        return (
            f"metadata substrate admission failed ({kind}) at {metadata_path}: "
            f"expected dict, list, or an E1-admitted ordinary Scalar carrier "
            f"({carrier_type_name})"
        )
    return (
        f"metadata substrate admission failed ({kind}) at {metadata_path}: "
        f"expected {expected_node_kind}"
    )


def _format_metadata_path(segments: list[_PathSegment]) -> str:
    rendered = ["_meta"]
    for segment_kind, segment_value in segments:
        if segment_kind == "key":
            rendered.append(f".{segment_value}")
        elif segment_kind == "index":
            rendered.append(f"[{segment_value}]")
        else:  # "entry" -- unsupported key, named only by ordinal
            rendered.append(f"[<entry {segment_value}>]")
    return "".join(rendered)


def _validate_dict_container(
    node: dict[Any, Any],
    *,
    segments: list[_PathSegment],
    active_ids: set[int],
) -> None:
    for ordinal, (key, value) in enumerate(node.items()):
        if type(key) is not str:
            raise MetadataSubstrateAdmissionError(
                kind="unsupported_metadata_key",
                metadata_path=_format_metadata_path(
                    segments + [("entry", ordinal)]
                ),
                expected_node_kind="str",
            )
        _validate_node(value, segments=segments + [("key", key)], active_ids=active_ids)


def _validate_list_container(
    node: list[Any],
    *,
    segments: list[_PathSegment],
    active_ids: set[int],
) -> None:
    for index, value in enumerate(node):
        _validate_node(value, segments=segments + [("index", index)], active_ids=active_ids)


def _validate_node(
    value: Any,
    *,
    segments: list[_PathSegment],
    active_ids: set[int],
) -> None:
    if type(value) is dict:
        _validate_container_with_cycle_guard(
            value, segments=segments, active_ids=active_ids, validate=_validate_dict_container
        )
        return
    if type(value) is list:
        _validate_container_with_cycle_guard(
            value, segments=segments, active_ids=active_ids, validate=_validate_list_container
        )
        return
    try:
        admit_ordinary_scalar(value)
    except OrdinaryScalarAdmissionError as error:
        raise MetadataSubstrateAdmissionError(
            kind="invalid_metadata_node",
            metadata_path=_format_metadata_path(segments),
            carrier_type_name=error.carrier_type_name,
        ) from None


_ContainerValidator = Callable[..., None]


def _validate_container_with_cycle_guard(
    node: Any,
    *,
    segments: list[_PathSegment],
    active_ids: set[int],
    validate: _ContainerValidator,
) -> None:
    node_id = id(node)
    if node_id in active_ids:
        raise MetadataSubstrateAdmissionError(
            kind="metadata_cycle_detected",
            metadata_path=_format_metadata_path(segments),
        )
    active_ids.add(node_id)
    try:
        validate(node, segments=segments, active_ids=active_ids)
    finally:
        active_ids.discard(node_id)


def admit_metadata_substrate(frames: Frames) -> Frames:
    """Return ``frames`` unchanged after validating ``_meta``'s complete substrate.

    A no-op (returns ``frames`` by identity) when ``_meta`` is absent or
    explicitly ``None`` -- both are the accepted "absent" root state. Read-only
    and non-mutating: every check below only inspects ``type(...)``/``id(...)``
    and delegates leaf classification to E1; nothing is rewritten, so a
    successful call returns the identical ``frames`` object and a failed call
    raises before returning, leaving the caller's object graph untouched.
    """
    meta = frames.get("_meta")
    if meta is None:
        return frames
    if type(meta) is not dict:
        raise MetadataSubstrateAdmissionError(
            kind="invalid_metadata_root",
            metadata_path="_meta",
            expected_node_kind="dict",
        )
    _validate_container_with_cycle_guard(
        meta, segments=[], active_ids=set(), validate=_validate_dict_container
    )
    return frames


__all__ = ["MetadataSubstrateAdmissionError", "admit_metadata_substrate"]
