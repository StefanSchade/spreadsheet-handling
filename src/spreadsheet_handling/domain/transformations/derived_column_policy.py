"""Reimport derived-column policy for business-facing workbook views.

Slice 1 of FTR-WORKBOOK-REIMPORT-DERIVED-COLUMN-POLICY-P4A.

This step consumes registered helper identity from transient
``_meta.derived`` provenance and durable metadata fallbacks.  It drops
helper/derived columns from a payload frame without column-name heuristics
and, in the mismatch policies, value-checks ``enrich_lookup`` helpers against
their source lookup frame.

FK ``helper_columns`` are dropped but not value-checked in this slice. Durable
file->frame reimport, sheet->frame view mapping, and derived-provenance
persistence are deferred (see the FTR backlog note).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.finding_frame import (
    FINDING_COLUMNS,
    Finding,
    findings_to_frame,
    simple_failure_message,
)
from spreadsheet_handling.domain.transformations.fk_helpers.policy import (
    resolve_v2_fk_relations,
)

Frames = dict[str, Any]

META_KEY = "_meta"

# Public name preserved for surface stability; the canonical model now lives in
# domain.finding_frame.  Every construction site passes ``severity`` explicitly.
DerivedColumnFinding = Finding

_VALID_POLICIES = {"drop", "warn_on_mismatch", "fail_on_mismatch"}


def apply_derived_column_policy(
    frames: Mapping[str, Any],
    *,
    source: str,
    output: str | None = None,
    policy: str = "drop",
    findings: str = "derived_column_findings",
    name: str | None = None,
) -> Frames:
    """Drop derived columns from a payload frame per the registered provenance.

    ``policy``:

    * ``drop`` — remove derived columns; no value comparison.
    * ``warn_on_mismatch`` — drop, value-check ``enrich_lookup`` helpers, and
      write a findings frame for mismatches without raising.
    * ``fail_on_mismatch`` — drop, value-check ``enrich_lookup`` helpers, and
      raise ``ValueError`` on any mismatch.

    Helper identity is resolved from transient ``_meta.derived.sheets[source]``
    when available. If that runtime provenance has already been stripped at a
    persistence boundary, ``policy: drop`` also honors durable workbook-view
    helper declarations at ``_meta.sheets[source].helper_columns`` and FK
    helper policy under ``_meta.helper_policies.fk``. Those fallback
    declarations identify columns only; mismatch value checks remain limited
    to the richer ``_meta.derived`` provenance.
    """
    del name
    policy = _valid_policy(policy)
    payload = _require_frame(frames, source)

    meta = frames.get(META_KEY) or {}
    sheet_meta = _safe_sheet_meta(meta, source)
    durable_helper_names = _safe_durable_helper_names(meta, source)
    policy_helper_names = _safe_policy_helper_names(frames, source)

    lookup_frames = {
        key: value
        for key, value in frames.items()
        if key != META_KEY and isinstance(value, pd.DataFrame)
    }

    cleaned, found = enforce_derived_column_policy_frame(
        payload,
        frame_name=source,
        derived_meta=sheet_meta,
        lookup_frames=lookup_frames,
        policy=policy,
        durable_helper_names=durable_helper_names | policy_helper_names,
    )

    failures = [finding for finding in found if finding.severity == "fail"]
    if policy == "fail_on_mismatch" and failures:
        raise ValueError(simple_failure_message(failures, heading="Derived column policy failed"))

    out = dict(frames)
    out[output or source] = cleaned
    if policy == "warn_on_mismatch":
        out[findings] = findings_to_frame(found, columns=FINDING_COLUMNS)

    # When the cleaned payload replaces the source frame, the consumed
    # provenance no longer describes any present column. Remove it and prune
    # empty containers. When `output` is a distinct frame, the original
    # helper-bearing source frame (and its provenance) is preserved untouched.
    replacing = output is None or output == source
    if replacing and sheet_meta:
        out[META_KEY] = _strip_consumed_provenance(meta, source)
    return out


def enforce_derived_column_policy_frame(
    payload: pd.DataFrame,
    *,
    frame_name: str,
    derived_meta: Mapping[str, Any] | None,
    lookup_frames: Mapping[str, pd.DataFrame],
    policy: str,
    durable_helper_names: set[str] | None = None,
) -> tuple[pd.DataFrame, list[DerivedColumnFinding]]:
    """Pure core: return (payload_without_derived_columns, findings).

    ``derived_meta`` is ``_meta["derived"]["sheets"].get(frame_name)`` or None.
    ``durable_helper_names`` comes from persisted workbook-view helper metadata
    and is used for identity/drop only. Value comparison covers
    ``enrich_lookup`` helpers only; FK helpers are dropped without a value
    check.
    """
    policy = _valid_policy(policy)
    helper_names, enrich_spec = _resolve_derived_identity(derived_meta, frame_name=frame_name)
    helper_names |= {str(name) for name in durable_helper_names or set()}

    findings: list[DerivedColumnFinding] = []
    if policy in ("warn_on_mismatch", "fail_on_mismatch") and enrich_spec is not None:
        severity = "fail" if policy == "fail_on_mismatch" else "warn"
        findings = _check_enrich_lookup_values(
            payload,
            frame_name=frame_name,
            spec=enrich_spec,
            lookup_frames=lookup_frames,
            severity=severity,
        )

    drop_cols = [col for col in payload.columns if _visible_label(col) in helper_names]
    keep_cols = [col for col in payload.columns if col not in drop_cols]
    return payload.loc[:, keep_cols], findings


def _resolve_derived_identity(
    derived_meta: Any,
    *,
    frame_name: str,
) -> tuple[set[str], Mapping[str, Any] | None]:
    """Resolve helper identity from sheet-level provenance.

    Missing provenance is a safe no-op. Malformed provenance fails with a
    clear ``ValueError`` naming the bad ``_meta.derived`` path rather than
    raising a raw ``AttributeError`` or silently treating it as valid.
    """
    if derived_meta is None:
        return set(), None
    if not isinstance(derived_meta, Mapping):
        raise ValueError(
            f"_meta.derived.sheets[{frame_name!r}] must be a mapping, "
            f"got {type(derived_meta).__name__}"
        )

    helper_names = _validated_fk_helper_names(
        derived_meta.get("helper_columns"), frame_name=frame_name
    )
    enrich_spec, enrich_names = _validated_enrich_spec(
        derived_meta.get("enrich_lookup"), frame_name=frame_name
    )
    helper_names |= enrich_names
    return helper_names, enrich_spec


def _validated_fk_helper_names(raw_helper_columns: Any, *, frame_name: str) -> set[str]:
    if raw_helper_columns is None:
        return set()
    if not isinstance(raw_helper_columns, (list, tuple)):
        raise ValueError(
            f"_meta.derived.sheets[{frame_name!r}].helper_columns must be a list"
        )
    names: set[str] = set()
    for index, entry in enumerate(raw_helper_columns):
        if not isinstance(entry, Mapping):
            raise ValueError(
                f"_meta.derived.sheets[{frame_name!r}].helper_columns[{index}] "
                f"must be a mapping, got {type(entry).__name__}"
            )
        column = entry.get("column")
        if column:
            names.add(str(column))
    return names


def _validated_enrich_spec(
    enrich_spec: Any,
    *,
    frame_name: str,
) -> tuple[Mapping[str, Any] | None, set[str]]:
    if enrich_spec is None:
        return None, set()
    if not isinstance(enrich_spec, Mapping):
        raise ValueError(
            f"_meta.derived.sheets[{frame_name!r}].enrich_lookup must be a mapping, "
            f"got {type(enrich_spec).__name__}"
        )
    raw_cols = enrich_spec.get("helper_columns")
    if raw_cols is not None and not isinstance(raw_cols, (list, tuple)):
        raise ValueError(
            f"_meta.derived.sheets[{frame_name!r}].enrich_lookup.helper_columns "
            f"must be a list"
        )
    return enrich_spec, {str(column) for column in raw_cols or []}


def _safe_sheet_meta(meta: Mapping[str, Any], source: str) -> Any:
    """Return ``_meta.derived.sheets[source]`` with clear errors on bad shapes.

    Missing ``derived`` / ``sheets`` is a safe no-op (returns None). A
    non-mapping ``derived`` or ``sheets`` container is malformed and fails
    with a clear ``ValueError`` naming the bad path.
    """
    derived = meta.get("derived")
    if derived is None:
        return None
    if not isinstance(derived, Mapping):
        raise ValueError(
            f"_meta.derived must be a mapping, got {type(derived).__name__}"
        )
    sheets = derived.get("sheets")
    if sheets is None:
        return None
    if not isinstance(sheets, Mapping):
        raise ValueError(
            f"_meta.derived.sheets must be a mapping, got {type(sheets).__name__}"
        )
    return sheets.get(source)


def _safe_durable_helper_names(meta: Mapping[str, Any], source: str) -> set[str]:
    """Return persisted workbook-view helper columns for ``source``.

    Missing durable metadata is a conservative no-op. Malformed present
    containers fail clearly because they are the declared cleanup carrier once
    transient ``_meta.derived`` has been stripped.
    """
    sheets = meta.get("sheets")
    if sheets is None:
        return set()
    if not isinstance(sheets, Mapping):
        raise ValueError(f"_meta.sheets must be a mapping, got {type(sheets).__name__}")
    sheet_entry = sheets.get(source)
    if sheet_entry is None:
        return set()
    if not isinstance(sheet_entry, Mapping):
        raise ValueError(
            f"_meta.sheets[{source!r}] must be a mapping, got {type(sheet_entry).__name__}"
        )
    raw_helper_columns = sheet_entry.get("helper_columns")
    if raw_helper_columns is None:
        return set()
    if not isinstance(raw_helper_columns, (list, tuple)):
        raise ValueError(f"_meta.sheets[{source!r}].helper_columns must be a list")
    return {str(column) for column in raw_helper_columns if str(column)}


def _safe_policy_helper_names(frames: Mapping[str, Any], source: str) -> set[str]:
    """Return FK helper columns declared for ``source``.

    The policy fallback is intentionally metadata-driven. It does not infer
    helper identity from column names, so unrelated underscore-prefixed columns
    remain payload.
    """
    helper_names = _v1_policy_helper_names(frames, source)
    relations = resolve_v2_fk_relations(dict(frames))
    if not relations:
        return helper_names
    for relation in relations:
        if str(relation.get("source_frame") or "") != source:
            continue
        for entry in relation.get("helper_columns") or []:
            if not isinstance(entry, Mapping):
                continue
            column = entry.get("column")
            if column:
                helper_names.add(str(column))
    return helper_names


def _v1_policy_helper_names(frames: Mapping[str, Any], source: str) -> set[str]:
    meta = frames.get(META_KEY)
    if not isinstance(meta, Mapping):
        return set()
    helper_policies = meta.get("helper_policies")
    if not isinstance(helper_policies, Mapping):
        return set()
    fk_policies = helper_policies.get("fk")
    if not isinstance(fk_policies, Mapping):
        return set()

    source_frame = frames.get(source)
    source_columns = {
        _visible_label(column)
        for column in getattr(source_frame, "columns", [])
    }
    if not source_columns:
        return set()

    helper_names: set[str] = set()
    for target_name, policy in fk_policies.items():
        if not isinstance(policy, Mapping):
            continue
        fk_column = str(policy.get("fk_column") or "")
        if not fk_column or fk_column not in source_columns:
            continue
        target_frame = str(policy.get("target_sheet") or policy.get("target") or target_name)
        raw_prefix = policy.get("helper_prefix")
        helper_prefix = "_" if raw_prefix is None else str(raw_prefix)
        for field in policy.get("default_helpers") or []:
            helper_names.add(f"{helper_prefix}{target_frame}_{str(field)}")
    return helper_names


def _strip_consumed_provenance(meta: Mapping[str, Any], source: str) -> dict[str, Any]:
    """Return a copy of ``meta`` with consumed provenance for ``source`` removed.

    Removes both ``helper_columns`` and ``enrich_lookup`` for the replaced
    source frame and prunes empty ``derived.sheets`` / ``derived`` containers.
    Copies only the mutated path; sibling sheets and the caller's input are
    left untouched.
    """
    new_meta = dict(meta)
    derived = new_meta.get("derived")
    if not isinstance(derived, Mapping):
        return new_meta
    derived = dict(derived)
    sheets = derived.get("sheets")
    if not isinstance(sheets, Mapping):
        return new_meta
    sheets = dict(sheets)

    sheet_entry = sheets.get(source)
    if isinstance(sheet_entry, Mapping):
        sheet_entry = dict(sheet_entry)
        sheet_entry.pop("helper_columns", None)
        sheet_entry.pop("enrich_lookup", None)
        if sheet_entry:
            sheets[source] = sheet_entry
        else:
            sheets.pop(source, None)

    if sheets:
        derived["sheets"] = sheets
    else:
        derived.pop("sheets", None)
    if derived:
        new_meta["derived"] = derived
    else:
        new_meta.pop("derived", None)
    return new_meta


def _check_enrich_lookup_values(
    payload: pd.DataFrame,
    *,
    frame_name: str,
    spec: Mapping[str, Any],
    lookup_frames: Mapping[str, pd.DataFrame],
    severity: str,
) -> list[DerivedColumnFinding]:
    lookup_name = str(spec.get("lookup") or "")
    on_keys = [str(key) for key in (spec.get("on") or [])]
    helper_cols = [str(col) for col in (spec.get("helper_columns") or [])]

    lookup_df = lookup_frames.get(lookup_name)
    if lookup_df is None:
        return [DerivedColumnFinding(
            rule_type="missing_lookup_frame",
            frame=frame_name,
            columns=helper_cols,
            row_index=None,
            value=None,
            severity=severity,
            message=f"Lookup frame {lookup_name!r} not available; cannot verify enrich_lookup helpers.",
        )]

    if not on_keys or not helper_cols:
        return []

    canonical = _canonical_value_map(lookup_df, on_keys=on_keys, helper_cols=helper_cols)

    findings: list[DerivedColumnFinding] = []
    for helper_col in helper_cols:
        if helper_col not in payload.columns:
            continue
        mismatching = _column_mismatch_indices(
            payload, helper_col=helper_col, on_keys=on_keys, canonical=canonical
        )
        if mismatching:
            findings.append(DerivedColumnFinding(
                rule_type="derived_value_mismatch",
                frame=frame_name,
                columns=[helper_col],
                row_index=tuple(mismatching),
                value=None,
                severity=severity,
                message=(
                    f"{len(mismatching)} row(s) differ from canonical lookup "
                    f"{lookup_name!r} for helper column {helper_col!r}."
                ),
            ))
    return findings


def _column_mismatch_indices(
    payload: pd.DataFrame,
    *,
    helper_col: str,
    on_keys: list[str],
    canonical: dict[tuple[Any, ...], dict[str, Any]],
) -> list[Any]:
    mismatching: list[Any] = []
    for row_index, row in payload.iterrows():
        key = tuple(_norm(row[k]) for k in on_keys if k in payload.columns)
        if len(key) != len(on_keys):
            continue
        canonical_row = canonical.get(key)
        if canonical_row is None:
            continue  # unresolved reference is a separate concern
        if _norm(row[helper_col]) != _norm(canonical_row.get(helper_col)):
            mismatching.append(row_index)
    return mismatching


def _canonical_value_map(
    lookup_df: pd.DataFrame,
    *,
    on_keys: list[str],
    helper_cols: list[str],
) -> dict[tuple[Any, ...], dict[str, Any]]:
    canonical: dict[tuple[Any, ...], dict[str, Any]] = {}
    for _, row in lookup_df.iterrows():
        if any(k not in lookup_df.columns for k in on_keys):
            break
        key = tuple(_norm(row[k]) for k in on_keys)
        if key in canonical:
            continue  # first occurrence wins (deterministic)
        canonical[key] = {col: row[col] for col in helper_cols if col in lookup_df.columns}
    return canonical


def _valid_policy(policy: str) -> str:
    if policy not in _VALID_POLICIES:
        raise ValueError(
            f"Unsupported policy {policy!r}; expected one of {sorted(_VALID_POLICIES)!r}"
        )
    return policy


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Frame {name!r} not found")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Frame {name!r} must be a pandas DataFrame")
    return frame


def _visible_label(col: Any) -> str:
    if isinstance(col, tuple):
        for part in col:
            label = str(part)
            if label:
                return label
        return ""
    return str(col)


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return str(value).strip()
