"""Lookup-owned mismatch evaluation for written ``enrich_lookup`` helpers.

F-002 Slice 2 (FK / Reference-Helper Domain-family hardening) relocates here
the mismatch-evaluation primitive that previously lived, unowned, inside
``derived_column_policy.py`` (``_check_enrich_lookup_values`` /
``_canonical_value_map`` / ``_column_mismatch_indices``). Lookup owns *what a
mismatch means* for its own helper columns: canonical lookup-map
construction, duplicate-key validity, scalar (values-mode) mismatch
evaluation, and :class:`~spreadsheet_handling.core.formulas.LookupFormulaSpec`
structural (formula-mode) mismatch evaluation. DCP (the composite) retains
*when* this check runs, warn/fail policy, severity, ``Finding`` construction,
``rule_type`` selection, aggregation, and the failure boundary -- see
:func:`evaluate_lookup_mismatches`'s return value, :class:`LookupMismatchReport`,
which deliberately carries no ``Finding``/severity/``rule_type`` information
of its own.

Two intentional, explicitly reviewed behavior corrections live here (accepted
design record
``docs/warm_storage/global_reviews/domain_fk_reference_helper_f002_implementation_readiness_2026-08-24.adoc``,
Sections 5 and 6):

* *Formula-mode structural comparison* replaces the former, defective
  ``str(LookupFormulaSpec)`` vs. plain-scalar comparison (FIND-C1-001): a
  formula-mode helper cell is compared structurally, on its own declared
  relationship-identity fields, against the expected relationship the
  interpreted provenance declares. This is only well-defined when the
  interpreted provenance is single-key; a multi-key formula-mode cell is
  reported as *unverifiable*, never certified valid or invalid, because the
  current single-key :class:`LookupFormulaSpec` representation cannot encode
  a multi-key relationship (F-CORR-2) -- see the module-level guard in
  :func:`evaluate_lookup_mismatches` below.
* *Duplicate lookup keys* on the current lookup frame make mismatch
  verification unverifiable, rather than DCP's former unowned "first
  occurrence wins" tie-break. This reuses the same non-raising duplicate-key
  predicate ``enrich_lookup/operation.py``'s existing raising check uses,
  extracted to :mod:`enrich_lookup.policy` as the shared, same-family, single
  source of truth for "does this lookup frame currently have duplicate keys."

Dispatch between the two comparison modes is per-cell, not per-column
(runtime ``isinstance(value, LookupFormulaSpec)``), not by any new metadata:
a formula-mode column with one row manually overwritten by a literal value is
therefore checked as a values-mode edit on that row alone, with no cross-row
leakage. An unresolved payload row (its join-key value has no match in the
current lookup frame) is left unchecked, matching current, deliberately
preserved behavior -- provenance does not record the original ``missing``
policy, so this evaluator does not infer or reproduce it (see the module's
governing design record, Section 6.2).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from spreadsheet_handling.core.formulas import LookupFormulaSpec

from .policy import _lookup_frame_has_duplicate_keys
from .provenance import InterpretedEnrichLookupProvenance

RowIndex = Any


@dataclass(frozen=True)
class LookupMismatchReport:
    """Small, structured Lookup-owned mismatch result.

    Deliberately carries no ``Finding``/severity/``rule_type`` -- DCP
    constructs its own findings from this value (composite/primitive
    contract). At most one of ``missing_lookup_frame`` /
    ``unverifiable_reason`` / non-empty mismatch mappings is meaningful per
    call: a missing lookup frame or an unverifiable condition (missing key
    columns, duplicate lookup keys, or a multi-key formula-mode cell) is
    reported instead of, not alongside, per-row mismatch detail.
    """

    missing_lookup_frame: bool = False
    unverifiable_reason: str | None = None
    value_mismatches: Mapping[str, tuple[RowIndex, ...]] = field(default_factory=dict)
    formula_mismatches: Mapping[str, tuple[RowIndex, ...]] = field(default_factory=dict)


def evaluate_lookup_mismatches(
    payload: pd.DataFrame,
    *,
    interpreted: InterpretedEnrichLookupProvenance,
    lookup_frames: Mapping[str, pd.DataFrame],
) -> LookupMismatchReport:
    """Evaluate ``enrich_lookup`` helper columns against the current lookup frame.

    ``interpreted`` is the already-validated, already-key-form-resolved
    provenance (:func:`~.provenance.interpret_written_enrich_lookup_provenance`).
    ``lookup_frames`` is every non-``_meta`` ``DataFrame`` currently in scope,
    keyed by frame name.
    """
    lookup_name = interpreted.lookup_name
    payload_keys = list(interpreted.payload_keys)
    lookup_keys = list(interpreted.lookup_keys)
    declared_helper_cols = list(interpreted.helper_columns)

    lookup_df = lookup_frames.get(lookup_name)
    if lookup_df is None:
        return LookupMismatchReport(missing_lookup_frame=True)

    if not payload_keys or not declared_helper_cols:
        return LookupMismatchReport()

    # Fail closed when the named key columns are absent: without them no row
    # can be verified, so certifying zero mismatches would be unsound.
    reasons: list[str] = []
    missing_payload = [key for key in payload_keys if key not in payload.columns]
    missing_lookup = [key for key in lookup_keys if key not in lookup_df.columns]
    if missing_payload:
        reasons.append(f"payload key column(s) {missing_payload} absent from payload frame")
    if missing_lookup:
        reasons.append(
            f"lookup key column(s) {missing_lookup} absent from lookup frame {lookup_name!r}"
        )
    if reasons:
        return LookupMismatchReport(unverifiable_reason="; ".join(reasons))

    present_helper_cols = [col for col in declared_helper_cols if col in payload.columns]
    if not present_helper_cols:
        return LookupMismatchReport()

    # Duplicate lookup keys on the *current* lookup frame make verification
    # unverifiable (intentional correction, replacing DCP's former unowned
    # "first occurrence wins" tie-break -- see module docstring).
    if _lookup_frame_has_duplicate_keys(lookup_df, lookup_keys):
        return LookupMismatchReport(
            unverifiable_reason=(
                f"lookup frame {lookup_name!r} contains duplicate keys on "
                f"{lookup_keys}; cannot verify enrich_lookup helpers"
            )
        )

    # Multi-key formula-mode carve-out (F-CORR-2, binding): a LookupFormulaSpec
    # is structurally a single-key representation
    # (source_key_column/lookup_key_column are each one column name). When the
    # interpreted provenance is multi-key, no formula cell in any helper
    # column can be structurally verified against it -- report unverifiable
    # for the whole call rather than truncating to index [0] and certifying a
    # (possibly broken) multi-key formula as structurally correct.
    multi_key = len(payload_keys) != 1 or len(lookup_keys) != 1
    if multi_key and _contains_formula_cell(payload, present_helper_cols):
        return LookupMismatchReport(
            unverifiable_reason=(
                f"enrich_lookup for lookup {lookup_name!r} declares a multi-key "
                f"relationship (payload keys {payload_keys}, lookup keys "
                f"{lookup_keys}) but at least one helper column holds a "
                "LookupFormulaSpec, which is a single-key representation and "
                "cannot structurally verify the declared multi-key enrich_lookup "
                "relationship"
            )
        )

    canonical = _canonical_value_map(
        lookup_df, on_keys=lookup_keys, helper_cols=present_helper_cols
    )

    value_mismatches: dict[str, tuple[RowIndex, ...]] = {}
    formula_mismatches: dict[str, tuple[RowIndex, ...]] = {}
    for helper_col in present_helper_cols:
        value_rows, formula_rows = _column_mismatch_indices(
            payload,
            helper_col=helper_col,
            payload_keys=payload_keys,
            lookup_key=lookup_keys[0],
            lookup_name=lookup_name,
            canonical=canonical,
        )
        if value_rows:
            value_mismatches[helper_col] = tuple(value_rows)
        if formula_rows:
            formula_mismatches[helper_col] = tuple(formula_rows)

    return LookupMismatchReport(
        value_mismatches=value_mismatches,
        formula_mismatches=formula_mismatches,
    )


def _contains_formula_cell(payload: pd.DataFrame, helper_cols: list[str]) -> bool:
    return any(
        isinstance(value, LookupFormulaSpec)
        for helper_col in helper_cols
        for value in payload[helper_col]
    )


def _column_mismatch_indices(
    payload: pd.DataFrame,
    *,
    helper_col: str,
    payload_keys: list[str],
    lookup_key: str,
    lookup_name: str,
    canonical: dict[tuple[Any, ...], dict[str, Any]],
) -> tuple[list[Any], list[Any]]:
    """Per-row, per-cell dispatch: formula cells compare structurally, plain
    scalars compare against the canonical lookup value. Multi-key formula
    cells never reach here (already routed to ``unverifiable_reason`` above),
    so the single-key structural comparison below always uses ``payload_keys[0]``/
    ``lookup_key`` safely.
    """
    value_mismatching: list[Any] = []
    formula_mismatching: list[Any] = []
    expected_formula = (lookup_name, payload_keys[0], lookup_key, helper_col)
    for row_index, row in payload.iterrows():
        key = tuple(_norm(row[k]) for k in payload_keys if k in payload.columns)
        if len(key) != len(payload_keys):
            continue
        canonical_row = canonical.get(key)
        if canonical_row is None:
            continue  # unresolved reference is a separate concern (Section 6.2)

        cell = row[helper_col]
        if isinstance(cell, LookupFormulaSpec):
            actual_formula = (
                cell.lookup_sheet,
                cell.source_key_column,
                cell.lookup_key_column,
                cell.lookup_value_column,
            )
            if actual_formula != expected_formula:
                formula_mismatching.append(row_index)
        else:
            if _norm(cell) != _norm(canonical_row.get(helper_col)):
                value_mismatching.append(row_index)
    return value_mismatching, formula_mismatching


def _canonical_value_map(
    lookup_df: pd.DataFrame,
    *,
    on_keys: list[str],
    helper_cols: list[str],
) -> dict[tuple[Any, ...], dict[str, Any]]:
    canonical: dict[tuple[Any, ...], dict[str, Any]] = {}
    for _, row in lookup_df.iterrows():
        key = tuple(_norm(row[k]) for k in on_keys)
        canonical[key] = {col: row[col] for col in helper_cols if col in lookup_df.columns}
    return canonical


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return str(value).strip()
