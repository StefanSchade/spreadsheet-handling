"""Reimport derived-column policy for business-facing workbook views.

Slice 1 of FTR-WORKBOOK-REIMPORT-DERIVED-COLUMN-POLICY-P4A.

This step consumes the transient ``_meta.derived`` channel in-memory, before
``drop_helpers`` cleanup, within a single pipeline run.  It drops
helper/derived columns from a payload frame using only registered provenance
(no column-name heuristics) and, in the mismatch policies, value-checks
``enrich_lookup`` helpers against their source lookup frame.

FK ``helper_columns`` are dropped but not value-checked in this slice because
FK provenance does not record the target key column.  Durable file->frame
reimport, sheet->frame view mapping, and derived-provenance persistence are
deferred (see the FTR backlog note).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

Frames = dict[str, Any]

META_KEY = "_meta"

FINDING_COLUMNS = [
    "rule_type",
    "frame",
    "columns",
    "row_index",
    "value",
    "severity",
    "message",
]

_VALID_POLICIES = {"drop", "warn_on_mismatch", "fail_on_mismatch"}


@dataclass(frozen=True)
class DerivedColumnFinding:
    rule_type: str
    frame: str
    columns: list[str]
    row_index: Any
    value: tuple[Any, ...] | None
    severity: str = "warn"
    message: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "rule_type": self.rule_type,
            "frame": self.frame,
            "columns": ", ".join(self.columns),
            "row_index": "" if self.row_index is None else _row_index_label(self.row_index),
            "value": "" if self.value is None else " | ".join(map(str, self.value)),
            "severity": self.severity,
            "message": self.message,
        }


def findings_to_frame(findings: Iterable[DerivedColumnFinding]) -> pd.DataFrame:
    return pd.DataFrame(
        [finding.to_record() for finding in findings],
        columns=FINDING_COLUMNS,
    )


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

    Helper identity comes only from ``_meta.derived.sheets[source]``.  Runs
    before ``drop_helpers``; if the channel is already cleaned it is a no-op
    for identity/value purposes.
    """
    del name
    policy = _valid_policy(policy)
    payload = _require_frame(frames, source)

    meta = frames.get(META_KEY) or {}
    derived_sheets = ((meta.get("derived") or {}).get("sheets") or {})
    sheet_meta = derived_sheets.get(source)

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
    )

    failures = [finding for finding in found if finding.severity == "fail"]
    if policy == "fail_on_mismatch" and failures:
        raise ValueError(_failure_message(failures))

    out = dict(frames)
    out[output or source] = cleaned
    if policy == "warn_on_mismatch":
        out[findings] = findings_to_frame(found)
    return out


def enforce_derived_column_policy_frame(
    payload: pd.DataFrame,
    *,
    frame_name: str,
    derived_meta: Mapping[str, Any] | None,
    lookup_frames: Mapping[str, pd.DataFrame],
    policy: str,
) -> tuple[pd.DataFrame, list[DerivedColumnFinding]]:
    """Pure core: return (payload_without_derived_columns, findings).

    ``derived_meta`` is ``_meta["derived"]["sheets"].get(frame_name)`` or None.
    Value comparison covers ``enrich_lookup`` helpers only; FK helpers are
    dropped without a value check.
    """
    policy = _valid_policy(policy)
    helper_names, enrich_spec = _resolve_derived_identity(derived_meta)

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
    derived_meta: Mapping[str, Any] | None,
) -> tuple[set[str], Mapping[str, Any] | None]:
    if not derived_meta:
        return set(), None

    helper_names: set[str] = set()
    for entry in derived_meta.get("helper_columns") or []:
        column = entry.get("column")
        if column:
            helper_names.add(str(column))

    enrich_spec = derived_meta.get("enrich_lookup")
    if isinstance(enrich_spec, Mapping):
        for column in enrich_spec.get("helper_columns") or []:
            helper_names.add(str(column))
    else:
        enrich_spec = None

    return helper_names, enrich_spec


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


def _row_index_label(row_index: Any) -> str:
    if isinstance(row_index, tuple):
        return ", ".join(map(str, row_index))
    return str(row_index)


def _failure_message(findings: list[DerivedColumnFinding]) -> str:
    lines = [f"{finding.rule_type}: {finding.message}" for finding in findings]
    return "Derived column policy failed:\n" + "\n".join(f"  - {line}" for line in lines)
