"""Pure domain validation functions for FK-helper consistency.

The validation primitives consume v2 FK relation policy under
``_meta.helper_policies.fk.relations`` and derived helper provenance under
``_meta.derived.sheets.*.helper_columns``. They never re-derive FK identity
from column names. Without policy or provenance, the FK-specific checks have
no declared relations to validate against and emit no findings; the
duplicate-id check still runs because it is independent of FK structure.

Refactored by ``FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5`` from the
previous convention-driven detection path.

All functions are stateless and return structured findings.
No logging, no exceptions for validation issues -- callers decide policy.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from ...frame_keys import iter_data_frames
from ...core.fk import normalize_sheet_key
from ...core.indexing import has_level0, level0_series
from ..transformations.fk_helpers import (
    derived_helper_columns_by_sheet,
    resolve_v2_fk_relations,
)
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
    """Report helper columns declared for one sheet that appear on another.

    With v2 policy a helper column is identified explicitly; arbitrary
    underscore-prefixed columns are no longer treated as 'looks-like-a-helper'.
    A helper column declared for one sheet showing up on another sheet
    *without* declaration on that sheet is still surfaced as unexpected.
    """
    del defaults
    findings: Findings = []
    expected_by_sheet = _expected_helper_columns_by_sheet(frames)
    if not expected_by_sheet:
        return findings

    cross_sheet_declared = {
        declared.helper_column
        for bucket in expected_by_sheet.values()
        for declared in bucket.declared_entries
    }

    for sheet_name, df in iter_data_frames(frames):
        expected = expected_by_sheet.get(sheet_name)
        declared_here = expected.declared_helper_columns if expected else set()
        first_cols = [
            (c[0] if isinstance(c, tuple) else c) for c in df.columns.tolist()
        ]
        for col in first_cols:
            col_s = str(col)
            if col_s in declared_here:
                continue
            if col_s in cross_sheet_declared:
                findings.append(Finding(
                    category="unexpected_helper",
                    sheet=sheet_name,
                    column=col_s,
                    detail=f"helper column '{col_s}' is not declared for sheet {sheet_name!r}",
                ))
    return findings


def check_missing_helpers(
    frames: Frames,
    defaults: Dict[str, Any] | None = None,
) -> Findings:
    """Report declared helper columns that are absent on their source frame."""
    del defaults
    findings: Findings = []
    expected_by_sheet = _expected_helper_columns_by_sheet(frames)
    if not expected_by_sheet:
        return findings

    for sheet_name, df in iter_data_frames(frames):
        expected = expected_by_sheet.get(sheet_name)
        if not expected:
            continue
        first_cols = set(
            (c[0] if isinstance(c, tuple) else c) for c in df.columns.tolist()
        )
        for declared in expected.declared_entries:
            helper_column = declared.helper_column
            if helper_column not in first_cols:
                findings.append(Finding(
                    category="missing_helper",
                    sheet=sheet_name,
                    column=helper_column,
                    detail=(
                        f"FK column '{declared.fk_column}' expects helper "
                        f"'{helper_column}'"
                    ),
                ))
    return findings


def check_helper_values(
    frames: Frames,
    defaults: Dict[str, Any] | None = None,
) -> Findings:
    """Report rows where helper values differ from the declared target lookup."""
    del defaults
    findings: Findings = []
    expected_by_sheet = _expected_helper_columns_by_sheet(frames)
    if not expected_by_sheet:
        return findings

    target_value_maps = _build_target_value_maps(frames, expected_by_sheet)

    def _norm(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, float) and pd.isna(v):
            return None
        return str(v).strip()

    for sheet_name, df in iter_data_frames(frames):
        expected = expected_by_sheet.get(sheet_name)
        if not expected:
            continue
        first_cols = set(
            (c[0] if isinstance(c, tuple) else c) for c in df.columns.tolist()
        )
        for declared in expected.declared_entries:
            if declared.helper_column not in first_cols:
                continue  # reported by check_missing_helpers
            target_map = target_value_maps.get(declared.target_frame, {}).get(
                declared.value_field, {}
            )
            try:
                fk_series = level0_series(df, declared.fk_column)
                helper_series = level0_series(df, declared.helper_column)
            except KeyError:
                continue

            mismatches = []
            for idx, (fk_val, helper_val) in enumerate(
                zip(fk_series.tolist(), helper_series.tolist())
            ):
                nk = _norm(fk_val)
                if nk is None:
                    continue
                expected_val = target_map.get(nk)
                actual = _norm(helper_val)
                exp_norm = _norm(expected_val)
                if actual != exp_norm:
                    mismatches.append(idx)

            if mismatches:
                n = len(mismatches)
                sample = mismatches[:3]
                findings.append(Finding(
                    category="value_mismatch",
                    sheet=sheet_name,
                    column=declared.helper_column,
                    detail=f"{n} row(s) differ from canonical lookup (rows {sample})",
                ))

    return findings


def check_unresolvable_fks(
    frames: Frames,
    defaults: Dict[str, Any] | None = None,
) -> Findings:
    """Report FK values that cannot be resolved against the declared target."""
    del defaults
    findings: Findings = []
    expected_by_sheet = _expected_helper_columns_by_sheet(frames)
    if not expected_by_sheet:
        return findings

    target_id_sets = _build_target_id_sets(frames, expected_by_sheet)

    def _norm(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, float) and pd.isna(v):
            return None
        return str(v).strip()

    for sheet_name, df in iter_data_frames(frames):
        expected = expected_by_sheet.get(sheet_name)
        if not expected:
            continue
        seen_fk_columns: set[str] = set()
        for declared in expected.declared_entries:
            if declared.fk_column in seen_fk_columns:
                continue
            seen_fk_columns.add(declared.fk_column)

            target_ids = target_id_sets.get(declared.target_frame, set())
            try:
                fk_series = level0_series(df, declared.fk_column)
            except KeyError:
                continue

            missing = sorted({
                str(v) for v in fk_series.dropna().unique()
                if _norm(v) not in target_ids
            })
            if missing:
                findings.append(Finding(
                    category="unresolvable_fk",
                    sheet=sheet_name,
                    column=declared.fk_column,
                    detail=(
                        f"values not found in {declared.target_frame!r}: "
                        f"{missing}"
                    ),
                ))

    return findings


def check_duplicate_ids(
    frames: Frames,
    defaults: Dict[str, Any] | None = None,
) -> Findings:
    """Detect duplicate IDs per sheet.

    Uses ``target_key`` from declared FK relations to identify each
    target frame's id column. Falls back to ``defaults['id_field']`` (or
    ``'id'``) for sheets not declared as FK targets, so a workbook without
    any FK relations still gets a basic uniqueness check.
    """
    defs = defaults or {}
    fallback_id_field = str(defs.get("id_field", "id"))
    findings: Findings = []
    target_id_fields = _target_id_fields(frames)

    for sheet_name, df in iter_data_frames(frames):
        id_field = target_id_fields.get(sheet_name, fallback_id_field)
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


# ---------------------------------------------------------------------------
# Internal resolution helpers
# ---------------------------------------------------------------------------

class _DeclaredHelper:
    __slots__ = (
        "fk_column",
        "helper_column",
        "target_frame",
        "target_key",
        "value_field",
    )

    def __init__(
        self,
        *,
        fk_column: str,
        helper_column: str,
        target_frame: str,
        target_key: str,
        value_field: str,
    ) -> None:
        self.fk_column = fk_column
        self.helper_column = helper_column
        self.target_frame = target_frame
        self.target_key = target_key
        self.value_field = value_field


class _ExpectedSheet:
    __slots__ = (
        "declared_entries",
        "declared_helper_columns",
    )

    def __init__(self) -> None:
        self.declared_entries: list[_DeclaredHelper] = []
        self.declared_helper_columns: set[str] = set()


def _expected_helper_columns_by_sheet(
    frames: Frames,
) -> dict[str, _ExpectedSheet]:
    relations = resolve_v2_fk_relations(frames) or []
    provenance = derived_helper_columns_by_sheet(frames)

    by_sheet: dict[str, _ExpectedSheet] = {}
    # Provenance first (per-sheet authoritative when present).
    for sheet_name, entries in provenance.items():
        bucket = by_sheet.setdefault(sheet_name, _ExpectedSheet())
        for entry in entries:
            declared = _DeclaredHelper(
                fk_column=str(entry.get("fk_column", "")),
                helper_column=str(entry.get("column", "")),
                target_frame=str(entry.get("target") or entry.get("target_frame") or ""),
                target_key=str(entry.get("target_key") or ""),
                value_field=str(entry.get("value_field", "")),
            )
            if not declared.helper_column or not declared.fk_column:
                continue
            bucket.declared_entries.append(declared)
            bucket.declared_helper_columns.add(declared.helper_column)

    # Relations only contribute when a sheet has no provenance.
    for relation in relations:
        source_frame = str(relation.get("source_frame", ""))
        if not source_frame:
            continue
        if source_frame in provenance:
            continue
        bucket = by_sheet.setdefault(source_frame, _ExpectedSheet())
        target_frame = str(relation.get("target_frame", ""))
        target_key = str(relation.get("target_key", ""))
        for entry in relation.get("helper_columns") or []:
            declared = _DeclaredHelper(
                fk_column=str(relation.get("source_column", "")),
                helper_column=str(entry.get("column", "")),
                target_frame=target_frame,
                target_key=target_key,
                value_field=str(entry.get("target_field", "")),
            )
            if not declared.helper_column or not declared.fk_column:
                continue
            bucket.declared_entries.append(declared)
            bucket.declared_helper_columns.add(declared.helper_column)

    return by_sheet


def _build_target_value_maps(
    frames: Frames,
    expected_by_sheet: dict[str, _ExpectedSheet],
) -> dict[str, dict[str, dict[str, Any]]]:
    needs: dict[str, dict[str, set[str]]] = {}
    for bucket in expected_by_sheet.values():
        for declared in bucket.declared_entries:
            sheet_needs = needs.setdefault(
                declared.target_frame,
                {"key": set(), "fields": set()},
            )
            sheet_needs["key"].add(declared.target_key)
            sheet_needs["fields"].add(declared.value_field)

    maps: dict[str, dict[str, dict[str, Any]]] = {}
    sheet_name_lookup = _sheet_name_lookup(frames)
    for target_frame, sheet_needs in needs.items():
        df = _resolve_target_dataframe(frames, target_frame, sheet_name_lookup)
        if df is None:
            maps[target_frame] = {}
            continue
        cols = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        target_maps: dict[str, dict[str, Any]] = {}
        for target_key in sheet_needs["key"]:
            if target_key not in cols:
                continue
            key_series = level0_series(df, target_key)
            for field in sheet_needs["fields"]:
                if field not in cols:
                    target_maps[field] = {}
                    continue
                value_series = level0_series(df, field)
                field_map: dict[str, Any] = {}
                for raw_key, raw_value in zip(
                    key_series.tolist(), value_series.tolist()
                ):
                    normalized_key = _norm_key(raw_key)
                    if normalized_key is not None:
                        field_map[normalized_key] = raw_value
                target_maps[field] = field_map
        maps[target_frame] = target_maps
    return maps


def _build_target_id_sets(
    frames: Frames,
    expected_by_sheet: dict[str, _ExpectedSheet],
) -> dict[str, set[str]]:
    target_keys: dict[str, str] = {}
    for bucket in expected_by_sheet.values():
        for declared in bucket.declared_entries:
            if declared.target_frame and declared.target_key:
                target_keys.setdefault(declared.target_frame, declared.target_key)

    id_sets: dict[str, set[str]] = {}
    sheet_name_lookup = _sheet_name_lookup(frames)
    for target_frame, target_key in target_keys.items():
        df = _resolve_target_dataframe(frames, target_frame, sheet_name_lookup)
        if df is None:
            id_sets[target_frame] = set()
            continue
        cols = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        if target_key not in cols:
            id_sets[target_frame] = set()
            continue
        key_series = level0_series(df, target_key)
        id_sets[target_frame] = {
            key for key in (_norm_key(value) for value in key_series.tolist())
            if key is not None
        }
    return id_sets


def _target_id_fields(frames: Frames) -> dict[str, str]:
    """Map *sheet name* to its declared ``target_key`` when that sheet is an FK target."""
    relations = resolve_v2_fk_relations(frames) or []
    provenance = derived_helper_columns_by_sheet(frames)

    target_keys: dict[str, str] = {}
    sheet_name_lookup = _sheet_name_lookup(frames)

    def _record(target_frame: str, target_key: str) -> None:
        if not target_frame or not target_key:
            return
        actual_sheet = _resolve_sheet_name(target_frame, sheet_name_lookup)
        if actual_sheet is None:
            return
        target_keys.setdefault(actual_sheet, target_key)

    for relation in relations:
        _record(str(relation.get("target_frame", "")), str(relation.get("target_key", "")))
    for entries in provenance.values():
        for entry in entries:
            target_frame = str(entry.get("target") or entry.get("target_frame") or "")
            target_key = str(entry.get("target_key") or "")
            _record(target_frame, target_key)
    return target_keys


def _sheet_name_lookup(frames: Frames) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for sheet_name, _df in iter_data_frames(frames):
        lookup[sheet_name] = sheet_name
        lookup.setdefault(normalize_sheet_key(sheet_name), sheet_name)
    return lookup


def _resolve_sheet_name(
    target_frame: str,
    sheet_name_lookup: dict[str, str],
) -> str | None:
    if target_frame in sheet_name_lookup:
        return sheet_name_lookup[target_frame]
    normalized = normalize_sheet_key(target_frame)
    return sheet_name_lookup.get(normalized)


def _resolve_target_dataframe(
    frames: Frames,
    target_frame: str,
    sheet_name_lookup: dict[str, str],
) -> pd.DataFrame | None:
    actual_sheet = _resolve_sheet_name(target_frame, sheet_name_lookup)
    if actual_sheet is None:
        return None
    df = frames.get(actual_sheet)
    if isinstance(df, pd.DataFrame):
        return df
    return None


def _norm_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return str(value).strip()
