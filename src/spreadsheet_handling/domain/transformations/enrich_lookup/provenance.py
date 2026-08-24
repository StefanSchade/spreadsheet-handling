"""Lookup-owned interpretation of written ``enrich_lookup`` provenance.

FK direct cleanup (``fk_helpers/drop.py``) may remove columns from a frame
that also carries a sibling ``_meta.derived.sheets.<sheet>.enrich_lookup``
provenance record. Whether that record is still truthful after the removal
is Lookup's own semantic call (H5 in the FK/Lookup Cycle-0 assessment): the
predicate depends only on Lookup's own declared ``helper_columns`` and the
frame's post-mutation column labels, never on FK relation shape or policy.
FK cleanup calls :func:`reconcile_enrich_lookup_provenance` after its own
column mutation instead of interpreting the record itself.

F-002 Slice 1 (FK / Reference-Helper Domain-family hardening) additionally
relocates here the *written*-provenance shape validation and symmetric/
asymmetric key-form interpretation that previously lived, unowned, inside
``derived_column_policy.py`` (``_validated_enrich_spec`` /
``_validated_mismatch_keys`` / ``_validated_symmetric_on`` /
``_validated_single_key``). Two entry points are exposed, deliberately kept
distinct rather than merged into one eager call, because the composite
(DCP) consumes them at two different, policy-gated points with different
laziness requirements:

* :func:`validated_enrich_lookup_helper_columns` -- shape-only validation of
  an already-extracted ``enrich_lookup`` record, returning only its declared
  helper-column identity. DCP calls this unconditionally, for every policy
  including ``drop``, to resolve which columns to drop. It deliberately does
  *not* resolve or validate join-key form: join-key form is only meaningful
  once a value-checking policy (``warn_on_mismatch``/``fail_on_mismatch``)
  is in effect, and ``drop`` must remain value-blind (a currently
  test-pinned invariant -- malformed/absent key-form provenance must not
  raise under ``drop``).
* :func:`interpret_written_enrich_lookup_provenance` -- the full
  interpretation (shape validation *and* key-form resolution), returning an
  immutable :class:`InterpretedEnrichLookupProvenance`. DCP calls this only
  from its own mismatch-checking path, which already runs only under
  ``warn_on_mismatch``/``fail_on_mismatch`` -- the same conditional gate the
  relocated key-form validation ran under before this change. Both entry
  points share the same shape-validation step internally
  (``_validated_enrich_record_shape``) so the record is never re-validated
  from scratch twice in one call.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InterpretedEnrichLookupProvenance:
    """Owner-local interpretation of a written ``enrich_lookup`` record.

    Shape already validated, symmetric/asymmetric key form already resolved
    to the semantic key tuples DCP's mismatch check needs. Deliberately
    small: no formula/value-mode information, no missing-key policy, no
    mismatch-evaluation semantics -- those remain out of scope for this
    value object (see F-002 Slice 1 scope; mismatch evaluation itself stays
    DCP-owned until a later slice).
    """

    lookup_name: str
    payload_keys: tuple[str, ...]
    lookup_keys: tuple[str, ...]
    helper_columns: tuple[str, ...]


def validated_enrich_lookup_helper_columns(
    record: Any, *, frame_name: str,
) -> tuple[str, ...]:
    """Validate an already-extracted ``enrich_lookup`` record's shape and
    return its declared helper-column names.

    ``record`` is ``_meta.derived.sheets[frame_name].enrich_lookup`` (or
    ``None`` when absent -- a safe no-op, matching the caller's existing
    "no enrich_lookup provenance" handling). Does not resolve or validate
    join-key form (see module docstring): callers that need the resolved
    key tuples use :func:`interpret_written_enrich_lookup_provenance`
    instead, at the point where key form actually becomes significant.

    Raises
    ------
    ValueError
        If ``record`` is present but not a mapping, or its ``helper_columns``
        member is present but not a list/tuple.
    """
    if record is None:
        return ()
    _, helper_columns = _validated_enrich_record_shape(record, frame_name=frame_name)
    return helper_columns


def interpret_written_enrich_lookup_provenance(
    record: Any, *, frame_name: str,
) -> InterpretedEnrichLookupProvenance:
    """Fully interpret a written, already-extracted ``enrich_lookup`` record.

    Performs exactly what the former ``_validated_enrich_spec`` +
    ``_validated_mismatch_keys`` + ``_validated_symmetric_on`` +
    ``_validated_single_key`` did together in ``derived_column_policy.py``:
    validate the record shape, resolve the symmetric/asymmetric key form,
    and return an immutable value exposing the semantic identity DCP's
    mismatch check needs. ``record`` must be present (callers only reach
    this once they have already established an ``enrich_lookup`` record
    exists, matching the current DCP call site's own guard).

    Raises
    ------
    ValueError
        On any malformed shape or key form, with the identical message and
        ``_meta.derived`` path wording the relocated code raised.
    """
    validated_record, helper_columns = _validated_enrich_record_shape(
        record, frame_name=frame_name
    )
    payload_keys, lookup_keys = _validated_mismatch_keys(
        validated_record, frame_name=frame_name
    )
    lookup_name = str(validated_record.get("lookup") or "")
    return InterpretedEnrichLookupProvenance(
        lookup_name=lookup_name,
        payload_keys=tuple(payload_keys),
        lookup_keys=tuple(lookup_keys),
        helper_columns=helper_columns,
    )


def _validated_enrich_record_shape(
    record: Any, *, frame_name: str,
) -> tuple[Mapping[str, Any], tuple[str, ...]]:
    if not isinstance(record, Mapping):
        raise ValueError(
            f"_meta.derived.sheets[{frame_name!r}].enrich_lookup must be a mapping, "
            f"got {type(record).__name__}"
        )
    raw_cols = record.get("helper_columns")
    if raw_cols is not None and not isinstance(raw_cols, (list, tuple)):
        raise ValueError(
            f"_meta.derived.sheets[{frame_name!r}].enrich_lookup.helper_columns "
            f"must be a list"
        )
    return record, tuple(str(column) for column in raw_cols or [])


def _validated_mismatch_keys(
    record: Mapping[str, Any],
    *,
    frame_name: str,
) -> tuple[list[str], list[str]]:
    """Resolve and *validate* ``(payload_keys, lookup_keys)`` from a record.

    The join-key form is selected from mapping-member *presence*, not from the
    truthiness or non-null value of a member (review R003-IMP-001). This keeps
    an absent member, a present ``None`` member, and a present record with no
    key form distinct — the earlier value-based detection conflated all three
    and let a degraded record fail open.

    Supports both provenance shapes written by ``enrich_lookup`` and validates
    the selected shape strictly before any coercion:

    * *symmetric* — a present ``on`` member selects the symmetric form and is
      always validated: ``on`` must be a non-empty list/tuple of non-empty
      strings (the writer's multi-key shape), so ``{"on": None}`` is rejected.
      The payload and lookup share the key name(s); ``payload_keys == lookup_keys``.
    * *asymmetric* — the presence of either ``source_key`` or ``lookup_key``
      selects the asymmetric form; both members must be present and each must be
      a single non-empty string, so a null half is rejected. The payload is
      keyed by ``source_key`` and the lookup frame by ``lookup_key``.

    Malformed provenance is rejected with a clear ``ValueError`` naming the
    ``_meta.derived`` path: a record must not carry ``on`` together with an
    asymmetric member (even when a value is ``None``), an asymmetric record must
    carry both non-empty halves, and no key value may be blank or a non-string.
    A *present* record with no join-key form at all is likewise malformed for a
    value-checking policy and is rejected (distinct from the absence of the
    whole ``enrich_lookup`` record, which the caller never routes here and which
    stays a safe no-op).
    """
    path = f"_meta.derived.sheets[{frame_name!r}].enrich_lookup"
    has_on = "on" in record
    has_source_key = "source_key" in record
    has_lookup_key = "lookup_key" in record

    if has_on and (has_source_key or has_lookup_key):
        raise ValueError(
            f"{path} mixes symmetric `on` with asymmetric "
            f"`source_key`/`lookup_key`; provide exactly one join-key form"
        )

    if has_on:
        on_keys = _validated_symmetric_on(record.get("on"), path=path)
        return on_keys, on_keys

    if has_source_key or has_lookup_key:
        missing = [
            name
            for name, present in (
                ("source_key", has_source_key),
                ("lookup_key", has_lookup_key),
            )
            if not present
        ]
        if missing:
            raise ValueError(
                f"{path} asymmetric provenance requires both `source_key` and "
                f"`lookup_key`; missing {missing}"
            )
        return (
            [_validated_single_key(record.get("source_key"), path=path, field="source_key")],
            [_validated_single_key(record.get("lookup_key"), path=path, field="lookup_key")],
        )

    raise ValueError(
        f"{path} has no join-key form; a value-checked enrich_lookup record must "
        f"declare either a symmetric `on` list or an asymmetric "
        f"`source_key`/`lookup_key` pair"
    )


def _validated_symmetric_on(on: Any, *, path: str) -> list[str]:
    if not isinstance(on, (list, tuple)):
        raise ValueError(
            f"{path}.on must be a non-empty list of key names; "
            f"got {type(on).__name__}"
        )
    if len(on) == 0:
        raise ValueError(f"{path}.on must be a non-empty list of key names; got an empty list")
    keys: list[str] = []
    for index, element in enumerate(on):
        if not isinstance(element, str):
            raise ValueError(
                f"{path}.on[{index}] must be a non-empty string key name; "
                f"got {type(element).__name__}"
            )
        if not element.strip():
            raise ValueError(f"{path}.on[{index}] must be a non-empty string key name; got a blank value")
        keys.append(element)
    return keys


def _validated_single_key(value: Any, *, path: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"{path}.{field} must be a single non-empty string key name; "
            f"got {type(value).__name__}"
        )
    if not value.strip():
        raise ValueError(
            f"{path}.{field} must be a single non-empty string key name; got a blank value"
        )
    return value


def reconcile_enrich_lookup_provenance(
    record: Any,
    *,
    frame_name: str,
    present_columns: Iterable[str],
) -> bool:
    """Decide whether *record* is still truthful after column removal.

    ``record`` is the current ``_meta.derived.sheets[frame_name].enrich_lookup``
    value (or any absent/malformed placeholder a caller might pass through).
    ``present_columns`` is the set of visible column labels remaining in
    *frame_name* after some other transformation has already run; this
    function does not know or care who performed that removal.

    Returns ``True`` when *record* should be retained: at least one of its
    declared ``helper_columns`` is still present. Returns ``False`` when none
    remain, meaning the record is stale and should be dropped. A non-mapping
    *record* is reported as "retain" -- interpreting a record shape that
    isn't a mapping at all is outside this seam's compatibility baseline and
    is left to the caller's existing handling.

    Raises
    ------
    ValueError
        If *record* is a mapping whose ``helper_columns`` is present but not
        a list/tuple. This is deliberate fail-clear hardening: previously
        this shape was silently misinterpreted (e.g. a string's characters or
        a dict's keys read as column names) or raised an opaque, untyped
        error from unrelated caller code. The message names the malformed
        ``_meta.derived`` path so the failure is traceable to Lookup's own
        provenance contract rather than to whichever caller triggered it.
    """
    if not isinstance(record, Mapping):
        return True
    raw_columns = record.get("helper_columns")
    if raw_columns is not None and not isinstance(raw_columns, (list, tuple)):
        raise ValueError(
            f"_meta.derived.sheets[{frame_name!r}].enrich_lookup.helper_columns "
            f"must be a list"
        )
    declared = {str(column) for column in raw_columns or []}
    return bool(declared & set(present_columns))
