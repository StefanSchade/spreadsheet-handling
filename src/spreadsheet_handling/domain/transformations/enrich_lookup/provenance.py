"""Lookup-owned reconciliation of ``enrich_lookup`` provenance after removal.

FK direct cleanup (``fk_helpers/drop.py``) may remove columns from a frame
that also carries a sibling ``_meta.derived.sheets.<sheet>.enrich_lookup``
provenance record. Whether that record is still truthful after the removal
is Lookup's own semantic call (H5 in the FK/Lookup Cycle-0 assessment): the
predicate depends only on Lookup's own declared ``helper_columns`` and the
frame's post-mutation column labels, never on FK relation shape or policy.
FK cleanup calls :func:`reconcile_enrich_lookup_provenance` after its own
column mutation instead of interpreting the record itself.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


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
