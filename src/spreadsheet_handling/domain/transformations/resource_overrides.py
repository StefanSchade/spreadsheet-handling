"""Generic resource override normalization for long-form tuple frames.

This module owns value semantics only.  It does not infer dense axes, workbook
views, locale meanings, or generated artifact output.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.finding_frame import (
    FINDING_COLUMNS,
    Finding,
    findings_to_frame,
    simple_failure_message,
)

Frames = dict[str, Any]

# Public name preserved for surface stability; the canonical model now lives in
# domain.finding_frame.  Every construction site passes ``severity`` explicitly,
# so the shared default differs harmlessly from the old class-level "fail".
ResourceOverrideFinding = Finding

_VALID_MODES = {"fail", "warn", "ignore"}
_VALID_EMPTY_OVERRIDE = {"omit_tuple", "keep_tuple"}


@dataclass(frozen=True)
class ResourceOverridePolicy:
    default_context: Any
    default_required: bool = True
    empty_override: str = "omit_tuple"
    explicit_empty_marker: Any | None = None
    collapse_override_equal_to_default: bool = True
    allow_empty_default: bool = False


@dataclass(frozen=True)
class ResourceOverrideNormalizationResult:
    frame: pd.DataFrame
    findings: list[ResourceOverrideFinding]


def normalize_resource_overrides(
    frames: Mapping[str, Any],
    *,
    source: str,
    row_keys: str | Iterable[str],
    discriminator_column: str,
    context_column: str,
    value_column: str,
    output: str | None = None,
    resource_override_policy: Mapping[str, Any] | None = None,
    default_context: Any | None = None,
    default_required: bool | None = None,
    empty_override: str | None = None,
    explicit_empty_marker: Any | None = None,
    collapse_override_equal_to_default: bool | None = None,
    allow_empty_default: bool | None = None,
    mode: str = "fail",
    findings: str = "resource_override_findings",
    name: str | None = None,
) -> Frames:
    """Normalize context override tuples in a frames-first pipeline step."""
    del name
    mode = _valid_mode(mode)
    source_frame = _require_frame(frames, source)
    row_key_cols = _as_list(row_keys, "row_keys")
    policy = _resource_override_policy(
        resource_override_policy,
        default_context=default_context,
        default_required=default_required,
        empty_override=empty_override,
        explicit_empty_marker=explicit_empty_marker,
        collapse_override_equal_to_default=collapse_override_equal_to_default,
        allow_empty_default=allow_empty_default,
    )

    result = normalize_resource_override_frame(
        source_frame,
        frame_name=source,
        row_keys=row_key_cols,
        discriminator_column=discriminator_column,
        context_column=context_column,
        value_column=value_column,
        policy=policy,
        severity=mode,
    )
    failures = [finding for finding in result.findings if finding.severity == "fail"]
    if mode == "fail" and failures:
        raise ValueError(
            simple_failure_message(failures, heading="Resource override normalization failed")
        )

    out: dict[str, Any] = dict(frames)
    out[output or source] = result.frame
    if mode == "warn":
        out[findings] = findings_to_frame(result.findings, columns=FINDING_COLUMNS)
    return out


def normalize_resource_override_frame(
    frame: pd.DataFrame,
    *,
    frame_name: str = "resource_overrides",
    row_keys: str | Iterable[str],
    discriminator_column: str,
    context_column: str,
    value_column: str,
    policy: ResourceOverridePolicy | Mapping[str, Any],
    severity: str = "fail",
) -> ResourceOverrideNormalizationResult:
    """Normalize context-specific overrides in a long-form tuple frame."""
    severity = _valid_mode(severity)
    row_key_cols = _as_list(row_keys, "row_keys")
    normalized_policy = (
        policy
        if isinstance(policy, ResourceOverridePolicy)
        else _resource_override_policy(policy)
    )
    _ensure_policy(normalized_policy)
    _ensure_columns(
        frame,
        [*row_key_cols, discriminator_column, context_column, value_column],
        frame_name=frame_name,
    )

    findings = _duplicate_findings(
        frame,
        frame_name=frame_name,
        key_columns=[*row_key_cols, discriminator_column, context_column],
        value_column=value_column,
        severity=severity,
    )
    canonical_rows = _first_rows_by_context(
        frame,
        key_columns=[*row_key_cols, discriminator_column, context_column],
    )
    findings.extend(
        _missing_default_findings(
            canonical_rows,
            frame_name=frame_name,
            row_keys=row_key_cols,
            discriminator_column=discriminator_column,
            context_column=context_column,
            value_column=value_column,
            policy=normalized_policy,
            severity=severity,
        )
    )

    output_rows = _normalized_rows(
        canonical_rows,
        row_keys=row_key_cols,
        discriminator_column=discriminator_column,
        context_column=context_column,
        value_column=value_column,
        policy=normalized_policy,
    )
    return ResourceOverrideNormalizationResult(
        frame=pd.DataFrame(output_rows, columns=list(frame.columns)),
        findings=findings,
    )


def _resource_override_policy(
    raw: Mapping[str, Any] | None = None,
    *,
    default_context: Any | None = None,
    default_required: bool | None = None,
    empty_override: str | None = None,
    explicit_empty_marker: Any | None = None,
    collapse_override_equal_to_default: bool | None = None,
    allow_empty_default: bool | None = None,
) -> ResourceOverridePolicy:
    values = dict(raw or {})
    if default_context is not None:
        values["default_context"] = default_context
    if default_required is not None:
        values["default_required"] = default_required
    if empty_override is not None:
        values["empty_override"] = empty_override
    if explicit_empty_marker is not None:
        values["explicit_empty_marker"] = explicit_empty_marker
    if collapse_override_equal_to_default is not None:
        values["collapse_override_equal_to_default"] = collapse_override_equal_to_default
    if allow_empty_default is not None:
        values["allow_empty_default"] = allow_empty_default

    unsupported = sorted(set(values) - set(ResourceOverridePolicy.__dataclass_fields__))
    if unsupported:
        raise ValueError(f"resource_override_policy contains unsupported key(s): {unsupported!r}")
    if "default_context" not in values:
        raise ValueError("resource_override_policy.default_context is required")
    return ResourceOverridePolicy(**values)


def _ensure_policy(policy: ResourceOverridePolicy) -> None:
    if policy.empty_override not in _VALID_EMPTY_OVERRIDE:
        raise ValueError(
            f"Unsupported empty_override {policy.empty_override!r}; "
            f"expected one of {sorted(_VALID_EMPTY_OVERRIDE)!r}"
        )


def _valid_mode(mode: str) -> str:
    if mode not in _VALID_MODES:
        raise ValueError(f"Unsupported mode {mode!r}; expected one of {sorted(_VALID_MODES)!r}")
    return mode


def _as_list(value: str | Iterable[str], field_name: str) -> list[str]:
    result = [value] if isinstance(value, str) else list(value)
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Frame {name!r} not found")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Frame {name!r} must be a pandas DataFrame")
    return frame


def _ensure_columns(df: pd.DataFrame, columns: Iterable[str], *, frame_name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"Frame {frame_name!r} is missing configured columns: {missing!r}")


def _duplicate_findings(
    frame: pd.DataFrame,
    *,
    frame_name: str,
    key_columns: list[str],
    value_column: str,
    severity: str,
) -> list[ResourceOverrideFinding]:
    duplicate_mask = frame.duplicated(subset=key_columns, keep=False)
    if not duplicate_mask.any():
        return []

    findings: list[ResourceOverrideFinding] = []
    for key, duplicate_rows in frame.loc[duplicate_mask].groupby(key_columns, dropna=False):
        values = duplicate_rows[value_column].tolist()
        conflicting = not _all_values_equal(values)
        row_index = tuple(duplicate_rows.index.tolist())
        findings.append(
            ResourceOverrideFinding(
                rule_type="conflicting_tuple" if conflicting else "duplicate_tuple",
                frame=frame_name,
                columns=key_columns,
                row_index=row_index,
                value=_key_tuple(key),
                severity=severity,
                message=(
                    "Duplicate override tuples must be resolved; values conflict."
                    if conflicting
                    else "Duplicate override tuples must be unique."
                ),
            )
        )
    return findings


def _first_rows_by_context(
    frame: pd.DataFrame,
    *,
    key_columns: list[str],
) -> list[pd.Series]:
    seen: set[tuple[Any, ...]] = set()
    rows: list[pd.Series] = []
    for _, row in frame.iterrows():
        key = tuple(row[column] for column in key_columns)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def _missing_default_findings(
    rows: list[pd.Series],
    *,
    frame_name: str,
    row_keys: list[str],
    discriminator_column: str,
    context_column: str,
    value_column: str,
    policy: ResourceOverridePolicy,
    severity: str,
) -> list[ResourceOverrideFinding]:
    if not policy.default_required:
        return []

    grouped = _rows_by_identity(rows, row_keys=row_keys, discriminator_column=discriminator_column)
    findings: list[ResourceOverrideFinding] = []
    for identity, identity_rows in grouped.items():
        default_rows = [
            row for row in identity_rows
            if _values_equal(row[context_column], policy.default_context)
        ]
        if not default_rows:
            findings.append(
                ResourceOverrideFinding(
                    rule_type="missing_default",
                    frame=frame_name,
                    columns=[*row_keys, discriminator_column, context_column],
                    row_index=None,
                    value=identity,
                    severity=severity,
                    message="Required default context tuple is missing.",
                )
            )
            continue
        default_value = _normalized_value(default_rows[0][value_column], policy)
        if _is_empty_cell(default_value) and not policy.allow_empty_default:
            findings.append(
                ResourceOverrideFinding(
                    rule_type="empty_required_default",
                    frame=frame_name,
                    columns=[*row_keys, discriminator_column, value_column],
                    row_index=default_rows[0].name,
                    value=identity,
                    severity=severity,
                    message="Required default context value must be non-empty.",
                )
            )
    return findings


def _normalized_rows(
    rows: list[pd.Series],
    *,
    row_keys: list[str],
    discriminator_column: str,
    context_column: str,
    value_column: str,
    policy: ResourceOverridePolicy,
) -> list[dict[Any, Any]]:
    grouped = _rows_by_identity(rows, row_keys=row_keys, discriminator_column=discriminator_column)
    default_values = _default_values_by_identity(
        grouped,
        context_column=context_column,
        value_column=value_column,
        policy=policy,
    )

    output_rows: list[dict[Any, Any]] = []
    for row in rows:
        identity = tuple(row[column] for column in [*row_keys, discriminator_column])
        context = row[context_column]
        explicit_empty = _is_explicit_empty_marker(row[value_column], policy)
        value = _normalized_value(row[value_column], policy)
        if not _values_equal(context, policy.default_context):
            if _should_omit_empty_override(value, policy) and not explicit_empty:
                continue
            default_value = default_values.get(identity)
            if (
                not explicit_empty
                and policy.collapse_override_equal_to_default
                and default_value is not None
                and _values_equal(value, default_value)
            ):
                continue
        record = row.to_dict()
        record[value_column] = value
        output_rows.append(record)
    return output_rows


def _rows_by_identity(
    rows: list[pd.Series],
    *,
    row_keys: list[str],
    discriminator_column: str,
) -> dict[tuple[Any, ...], list[pd.Series]]:
    grouped: dict[tuple[Any, ...], list[pd.Series]] = {}
    for row in rows:
        identity = tuple(row[column] for column in [*row_keys, discriminator_column])
        grouped.setdefault(identity, []).append(row)
    return grouped


def _default_values_by_identity(
    grouped: Mapping[tuple[Any, ...], list[pd.Series]],
    *,
    context_column: str,
    value_column: str,
    policy: ResourceOverridePolicy,
) -> dict[tuple[Any, ...], Any]:
    values: dict[tuple[Any, ...], Any] = {}
    for identity, rows in grouped.items():
        for row in rows:
            if _values_equal(row[context_column], policy.default_context):
                values[identity] = _normalized_value(row[value_column], policy)
                break
    return values


def _normalized_value(value: Any, policy: ResourceOverridePolicy) -> Any:
    if _is_explicit_empty_marker(value, policy):
        return ""
    return value


def _is_explicit_empty_marker(value: Any, policy: ResourceOverridePolicy) -> bool:
    return (
        policy.explicit_empty_marker is not None
        and _values_equal(value, policy.explicit_empty_marker)
    )


def _should_omit_empty_override(value: Any, policy: ResourceOverridePolicy) -> bool:
    return policy.empty_override == "omit_tuple" and _is_empty_cell(value)


def _is_empty_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _all_values_equal(values: list[Any]) -> bool:
    if not values:
        return True
    first = values[0]
    return all(_values_equal(first, value) for value in values[1:])


def _values_equal(left: Any, right: Any) -> bool:
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _key_tuple(value: Any) -> tuple[Any, ...]:
    if isinstance(value, tuple):
        return value
    return (value,)
