"""Pure domain validation functions for FK-helper consistency.

All functions are stateless and return structured findings.
No logging, no exceptions for validation issues — callers decide policy.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from ...core.fk import (
    FKDef,
    build_registry,
    build_id_label_maps,
    detect_fk_columns,
)
from ...core.indexing import has_level0, level0_series
from .findings import Finding


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------

FKFinding = Finding  # tests may import FKFinding — it's now just Finding

Findings = List[Finding]
Frames = Dict[str, pd.DataFrame]


# ---------------------------------------------------------------------------
# Public validation functions
# ---------------------------------------------------------------------------

def check_unexpected_helpers(
    frames: Frames,
    defaults: Dict[str, Any] | None = None,
) -> Findings:
    """Detect helper columns that do not correspond to any known FK column."""
    defs = defaults or {}
    helper_prefix = str(defs.get("helper_prefix", "_"))
    reg = build_registry(frames, defs)
    findings: Findings = []

    for sheet_name, df in frames.items():
        fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
        expected_helpers = {fk.helper_column for fk in fk_defs}

        first_cols = [
            (c[0] if isinstance(c, tuple) else c) for c in df.columns.tolist()
        ]
        for col in first_cols:
            col_s = str(col)
            if col_s.startswith(helper_prefix) and col_s not in expected_helpers:
                findings.append(Finding(
                    category="unexpected_helper",
                    sheet=sheet_name,
                    column=col_s,
                    detail=f"helper column '{col_s}' has no matching FK column",
                ))

    return findings


def check_missing_helpers(
    frames: Frames,
    defaults: Dict[str, Any] | None = None,
) -> Findings:
    """Detect FK columns whose expected helper column is absent."""
    defs = defaults or {}
    helper_prefix = str(defs.get("helper_prefix", "_"))
    reg = build_registry(frames, defs)
    findings: Findings = []

    for sheet_name, df in frames.items():
        fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
        first_cols = set(
            (c[0] if isinstance(c, tuple) else c) for c in df.columns.tolist()
        )
        for fk in fk_defs:
            if fk.helper_column not in first_cols:
                findings.append(Finding(
                    category="missing_helper",
                    sheet=sheet_name,
                    column=fk.helper_column,
                    detail=f"FK column '{fk.fk_column}' expects helper '{fk.helper_column}'",
                ))

    return findings


def check_helper_values(
    frames: Frames,
    defaults: Dict[str, Any] | None = None,
) -> Findings:
    """Detect rows where the helper column value differs from the canonical lookup."""
    defs = defaults or {}
    helper_prefix = str(defs.get("helper_prefix", "_"))
    reg = build_registry(frames, defs)
    id_maps = build_id_label_maps(frames, reg)
    findings: Findings = []

    def _norm(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, float) and pd.isna(v):
            return None
        return str(v).strip()

    for sheet_name, df in frames.items():
        fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
        first_cols = set(
            (c[0] if isinstance(c, tuple) else c) for c in df.columns.tolist()
        )

        for fk in fk_defs:
            if fk.helper_column not in first_cols:
                continue  # missing helper — reported by check_missing_helpers

            target_map = id_maps.get(fk.target_sheet_key, {})
            try:
                fk_series = level0_series(df, fk.fk_column)
                helper_series = level0_series(df, fk.helper_column)
            except KeyError:
                continue

            mismatches = []
            for idx, (fk_val, helper_val) in enumerate(
                zip(fk_series.tolist(), helper_series.tolist())
            ):
                nk = _norm(fk_val)
                if nk is None:
                    continue
                expected = target_map.get(nk)
                actual = _norm(helper_val)
                exp_norm = _norm(expected)
                if actual != exp_norm:
                    mismatches.append(idx)

            if mismatches:
                n = len(mismatches)
                sample = mismatches[:3]
                findings.append(Finding(
                    category="value_mismatch",
                    sheet=sheet_name,
                    column=fk.helper_column,
                    detail=f"{n} row(s) differ from canonical lookup (rows {sample})",
                ))

    return findings


def check_unresolvable_fks(
    frames: Frames,
    defaults: Dict[str, Any] | None = None,
) -> Findings:
    """Detect FK values that cannot be resolved in the target sheet."""
    defs = defaults or {}
    helper_prefix = str(defs.get("helper_prefix", "_"))
    reg = build_registry(frames, defs)
    id_maps = build_id_label_maps(frames, reg)
    findings: Findings = []

    def _norm(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, float) and pd.isna(v):
            return None
        return str(v).strip()

    for sheet_name, df in frames.items():
        fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
        for fk in fk_defs:
            target_map = id_maps.get(fk.target_sheet_key, {})
            try:
                fk_series = level0_series(df, fk.fk_column)
            except KeyError:
                continue

            missing = sorted({
                str(v) for v in fk_series.dropna().unique()
                if _norm(v) not in target_map
            })
            if missing:
                findings.append(Finding(
                    category="unresolvable_fk",
                    sheet=sheet_name,
                    column=fk.fk_column,
                    detail=f"values not found in '{fk.target_sheet_key}': {missing}",
                ))

    return findings


def check_duplicate_ids(
    frames: Frames,
    defaults: Dict[str, Any] | None = None,
) -> Findings:
    """Detect duplicate IDs per sheet."""
    defs = defaults or {}
    id_field = str(defs.get("id_field", "id"))
    findings: Findings = []

    for sheet_name, df in frames.items():
        if not has_level0(df, id_field):
            continue
        ids = level0_series(df, id_field).astype("string")
        counts = ids.value_counts(dropna=False)
        dups = [str(idx) for idx, cnt in counts.items() if cnt > 1 and str(idx) != "nan"]
        if dups:
            findings.append(Finding(
                category="duplicate_id",
                sheet=sheet_name,
                column=id_field,
                detail=f"duplicate values: {dups}",
            ))

    return findings


def validate_fk_helpers(
    frames: Frames,
    defaults: Dict[str, Any] | None = None,
) -> Findings:
    """Run all FK-helper validation checks and return combined findings."""
    return (
        check_duplicate_ids(frames, defaults)
        + check_unresolvable_fks(frames, defaults)
        + check_unexpected_helpers(frames, defaults)
        + check_missing_helpers(frames, defaults)
        + check_helper_values(frames, defaults)
    )
