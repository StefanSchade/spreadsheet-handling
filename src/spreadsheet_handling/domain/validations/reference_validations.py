"""Declarative table key and reference validations."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.finding_frame import findings_to_frame as _serialize_findings

Frames = dict[str, Any]

# Module-specific extension of the canonical finding schema: reference
# validations additionally carry ``target_frame`` / ``target_columns`` and
# render ``row_index`` / ``value`` differently (raw index, JSON-encoded tuple),
# so this producer keeps its own column list and ``ReferenceFinding`` record.
# Only the tabular serialization mechanic is shared (see findings_to_frame).
FINDING_COLUMNS = [
    "rule_type",
    "frame",
    "columns",
    "row_index",
    "value",
    "target_frame",
    "target_columns",
    "severity",
    "message",
]

_VALID_MODES = {"warn", "fail", "ignore"}
_VALID_RULE_TYPES = {"unique", "primary_key", "foreign_key", "unique_reference"}
_CONDITION_PREDICATES = {"equals", "in", "non_empty", "is_null", "not_null"}


@dataclass(frozen=True)
class ReferenceFinding:
    rule_type: str
    frame: str
    columns: list[str]
    row_index: Any
    value: tuple[Any, ...] | None
    target_frame: str = ""
    target_columns: list[str] | None = None
    severity: str = "warn"
    message: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "rule_type": self.rule_type,
            "frame": self.frame,
            "columns": _format_columns(self.columns),
            "row_index": "" if self.row_index is None else self.row_index,
            "value": "" if self.value is None else _format_value(self.value),
            "target_frame": self.target_frame,
            "target_columns": _format_columns(self.target_columns or []),
            "severity": self.severity,
            "message": self.message,
        }


def validate_references(
    frames: Mapping[str, Any],
    *,
    rules: list[dict[str, Any]],
    mode: str = "warn",
    findings: str = "validation_findings",
    name: str | None = None,
) -> Frames:
    """Validate declarative key and reference rules against data frames."""
    mode = _valid_mode(mode)
    findings_frame = _valid_findings_name(findings)
    validation_findings = _validate_rules(frames, rules=rules, severity=mode)

    failures = _failure_findings(validation_findings)
    if mode == "fail" and failures:
        raise ValueError(_failure_message(failures, name=name))

    if mode != "warn":
        return dict(frames)

    out = dict(frames)
    out[findings_frame] = findings_to_frame(validation_findings)
    return out


def findings_to_frame(findings: Iterable[ReferenceFinding]) -> pd.DataFrame:
    """Convert reference validation findings to the stable report frame shape."""
    return _serialize_findings(findings, columns=FINDING_COLUMNS)


def _validate_rules(
    frames: Mapping[str, Any],
    *,
    rules: list[dict[str, Any]],
    severity: str,
) -> list[ReferenceFinding]:
    if not isinstance(rules, list):
        raise TypeError("validate_references rules must be a list of rule mappings")

    findings: list[ReferenceFinding] = []
    for position, rule in enumerate(rules, start=1):
        if not isinstance(rule, Mapping):
            raise TypeError(f"validate_references rule #{position} must be a mapping")
        rule_type = rule.get("type")
        if rule_type not in _VALID_RULE_TYPES:
            raise ValueError(
                f"Unsupported reference validation rule type {rule_type!r}; "
                f"expected one of {sorted(_VALID_RULE_TYPES)!r}"
            )
        enabled, skipped = _resolve_enabled_when(frames, rule=rule, rule_type=str(rule_type))
        findings.extend(skipped)
        if not enabled:
            continue

        if rule_type == "unique":
            findings.extend(_validate_unique(frames, rule=rule, severity=severity))
        elif rule_type == "primary_key":
            findings.extend(_validate_primary_key(frames, rule=rule, severity=severity))
        elif rule_type == "foreign_key":
            findings.extend(_validate_foreign_key(frames, rule=rule, severity=severity))
        elif rule_type == "unique_reference":
            findings.extend(_validate_unique_reference(frames, rule=rule, severity=severity))
    return findings


def _validate_unique(
    frames: Mapping[str, Any],
    *,
    rule: Mapping[str, Any],
    severity: str,
) -> list[ReferenceFinding]:
    frame_name, columns = _frame_and_columns(rule)
    frame = _optional_frame(frames, frame_name)
    missing = _missing_rule_columns(frame, columns)
    if frame is None or missing:
        return [_schema_finding("unique", frame_name, columns, missing, severity)]
    frame, skipped = _apply_when(frame, rule=rule, rule_type="unique", frame_name=frame_name, columns=columns)
    return skipped + _duplicate_findings(
        "unique",
        frame_name=frame_name,
        frame=frame,
        columns=columns,
        severity=severity,
        message="Configured columns must be unique.",
    )


def _validate_primary_key(
    frames: Mapping[str, Any],
    *,
    rule: Mapping[str, Any],
    severity: str,
) -> list[ReferenceFinding]:
    frame_name, columns = _frame_and_columns(rule)
    frame = _optional_frame(frames, frame_name)
    missing = _missing_rule_columns(frame, columns)
    if frame is None or missing:
        return [_schema_finding("primary_key", frame_name, columns, missing, severity)]
    frame, skipped = _apply_when(
        frame,
        rule=rule,
        rule_type="primary_key",
        frame_name=frame_name,
        columns=columns,
    )

    findings: list[ReferenceFinding] = list(skipped)
    for row_index, key in _row_keys(frame, columns):
        if any(_is_empty_cell(value) for value in key):
            findings.append(
                ReferenceFinding(
                    rule_type="primary_key",
                    frame=frame_name,
                    columns=columns,
                    row_index=row_index,
                    value=key,
                    severity=severity,
                    message="Primary key values must be present and non-empty.",
                )
            )

    complete_frame = frame.loc[
        [not any(_is_empty_cell(value) for value in key) for _, key in _row_keys(frame, columns)]
    ]
    findings.extend(
        _duplicate_findings(
            "primary_key",
            frame_name=frame_name,
            frame=complete_frame,
            columns=columns,
            severity=severity,
            message="Primary key values must be unique.",
        )
    )
    return findings


def _validate_foreign_key(
    frames: Mapping[str, Any],
    *,
    rule: Mapping[str, Any],
    severity: str,
) -> list[ReferenceFinding]:
    frame_name, columns = _frame_and_columns(rule)
    target_name = _string_field(rule, "target")
    target_columns = (
        _string_list(rule["target_columns"], "target_columns")
        if rule.get("target_columns") is not None
        else list(columns)
    )
    allow_empty = bool(rule.get("allow_empty", True))

    source = _optional_frame(frames, frame_name)
    target = _optional_frame(frames, target_name)
    missing_source = _missing_rule_columns(source, columns)
    missing_target = _missing_rule_columns(target, target_columns)
    findings: list[ReferenceFinding] = []
    if source is None or missing_source:
        findings.append(
            _schema_finding(
                "foreign_key",
                frame_name,
                columns,
                missing_source,
                severity,
                target_frame=target_name,
                target_columns=target_columns,
            )
        )
    if target is None or missing_target:
        findings.append(
            _schema_finding(
                "foreign_key",
                target_name,
                target_columns,
                missing_target,
                severity,
            )
        )
    if findings:
        return findings

    assert source is not None
    assert target is not None
    source, skipped = _apply_when(
        source,
        rule=rule,
        rule_type="foreign_key",
        frame_name=frame_name,
        columns=columns,
    )
    findings.extend(skipped)
    target_keys = {
        _key_token(key)
        for _, key in _row_keys(target, target_columns)
        if not any(_is_empty_cell(value) for value in key)
    }

    for row_index, key in _row_keys(source, columns):
        if all(_is_empty_cell(value) for value in key) and allow_empty:
            continue
        if any(_is_empty_cell(value) for value in key):
            findings.append(
                ReferenceFinding(
                    rule_type="foreign_key",
                    frame=frame_name,
                    columns=columns,
                    row_index=row_index,
                    value=key,
                    target_frame=target_name,
                    target_columns=target_columns,
                    severity=severity,
                    message="Foreign key contains empty key part.",
                )
            )
            continue
        if _key_token(key) not in target_keys:
            findings.append(
                ReferenceFinding(
                    rule_type="foreign_key",
                    frame=frame_name,
                    columns=columns,
                    row_index=row_index,
                    value=key,
                    target_frame=target_name,
                    target_columns=target_columns,
                    severity=severity,
                    message="Foreign key value is not present in target frame.",
                )
            )
    return findings


def _validate_unique_reference(
    frames: Mapping[str, Any],
    *,
    rule: Mapping[str, Any],
    severity: str,
) -> list[ReferenceFinding]:
    if bool(rule.get("allow_duplicates", False)):
        return []
    frame_name, columns = _frame_and_columns(rule)
    frame = _optional_frame(frames, frame_name)
    missing = _missing_rule_columns(frame, columns)
    if frame is None or missing:
        return [_schema_finding("unique_reference", frame_name, columns, missing, severity)]
    frame, skipped = _apply_when(
        frame,
        rule=rule,
        rule_type="unique_reference",
        frame_name=frame_name,
        columns=columns,
    )
    return skipped + _duplicate_findings(
        "unique_reference",
        frame_name=frame_name,
        frame=frame,
        columns=columns,
        severity=severity,
        message="Reference tuples must not be duplicated.",
    )


def _resolve_enabled_when(
    frames: Mapping[str, Any],
    *,
    rule: Mapping[str, Any],
    rule_type: str,
) -> tuple[bool, list[ReferenceFinding]]:
    condition = rule.get("enabled_when")
    if condition is None:
        return True, []
    if not isinstance(condition, Mapping):
        raise TypeError("enabled_when must be a mapping")

    optional = bool(condition.get("optional", False))
    switch_frame_name = _condition_string(condition, "frame", context="enabled_when")
    switch_frame = _optional_frame(frames, switch_frame_name)
    if switch_frame is None:
        if optional:
            return False, [_skipped_rule(rule_type, rule, "enabled_when switch frame is missing")]
        raise KeyError(f"enabled_when switch frame {switch_frame_name!r} not found")

    key_column = str(condition.get("key_column", "key"))
    if not key_column.strip():
        raise ValueError("enabled_when.key_column must be a non-empty string")
    if key_column not in switch_frame.columns:
        if optional:
            return False, [_skipped_rule(rule_type, rule, f"enabled_when key column {key_column!r} is missing")]
        raise KeyError(
            f"enabled_when key column {key_column!r} not found in switch frame "
            f"{switch_frame_name!r}"
        )
    if "key" not in condition:
        raise ValueError("enabled_when.key is required")

    key_value = _plain_value(condition["key"])
    matches = switch_frame.loc[
        switch_frame[key_column].map(_plain_value).map(_format_scalar) == _format_scalar(key_value)
    ]
    if matches.empty:
        if optional:
            return False, [_skipped_rule(rule_type, rule, f"enabled_when key {_format_scalar(key_value)!r} is missing")]
        raise KeyError(
            f"enabled_when key {_format_scalar(key_value)!r} not found in "
            f"{switch_frame_name!r}.{key_column}"
        )
    if len(matches.index) > 1:
        raise ValueError(
            f"enabled_when key {_format_scalar(key_value)!r} is not unique in "
            f"{switch_frame_name!r}.{key_column}"
        )

    mask = _condition_mask(
        matches,
        condition,
        frame_name=switch_frame_name,
        context="enabled_when",
        optional_missing=optional,
    )
    if mask is None:
        return False, [_skipped_rule(rule_type, rule, "enabled_when predicate column is missing")]
    enabled = bool(mask.iloc[0])
    if enabled:
        return True, []
    return False, [_skipped_rule(rule_type, rule, f"enabled_when did not match: {_condition_summary(condition)}")]


def _apply_when(
    frame: pd.DataFrame,
    *,
    rule: Mapping[str, Any],
    rule_type: str,
    frame_name: str,
    columns: list[str],
) -> tuple[pd.DataFrame, list[ReferenceFinding]]:
    condition = rule.get("when")
    if condition is None:
        return frame, []
    if not isinstance(condition, Mapping):
        raise TypeError("when must be a mapping")
    mask = _condition_mask(frame, condition, frame_name=frame_name, context="when")
    assert mask is not None
    skipped_count = int((~mask).sum())
    if skipped_count == 0:
        return frame.loc[mask].copy(), []
    return frame.loc[mask].copy(), [
        ReferenceFinding(
            rule_type=rule_type,
            frame=frame_name,
            columns=columns,
            row_index=None,
            value=None,
            severity="skipped",
            message=(
                f"Skipped {skipped_count} row(s) because when did not match: "
                f"{_condition_summary(condition)}."
            ),
        )
    ]


def _condition_mask(
    frame: pd.DataFrame,
    condition: Mapping[str, Any],
    *,
    frame_name: str,
    context: str,
    optional_missing: bool = False,
) -> pd.Series | None:
    column = _condition_string(condition, "column", context=context)
    unsupported = [
        key
        for key in condition
        if key
        not in {
            *_CONDITION_PREDICATES,
            "column",
            "frame",
            "key",
            "key_column",
            "optional",
        }
    ]
    if unsupported:
        raise ValueError(
            f"Unsupported {context} predicate key(s) {unsupported!r}; "
            f"supported predicates are {sorted(_CONDITION_PREDICATES)!r}"
        )
    predicates = [key for key in condition if key in _CONDITION_PREDICATES]
    if len(predicates) != 1:
        raise ValueError(
            f"{context} must configure exactly one predicate among "
            f"{sorted(_CONDITION_PREDICATES)!r}"
        )
    if column not in frame.columns:
        if optional_missing:
            return None
        raise KeyError(f"{context} column {column!r} not found in frame {frame_name!r}")

    predicate = predicates[0]
    values = frame[column]
    if predicate == "equals":
        return values.map(_plain_value).map(_format_scalar) == _format_scalar(
            _plain_value(condition[predicate])
        )
    if predicate == "in":
        members = condition[predicate]
        if isinstance(members, (str, bytes)) or not isinstance(members, Iterable):
            raise TypeError(f"{context}.in must be a list of allowed values, not a scalar")
        normalized_members = {_format_scalar(_plain_value(member)) for member in members}
        return values.map(_plain_value).map(_format_scalar).isin(normalized_members)
    if predicate == "non_empty":
        _ensure_boolean_predicate(condition[predicate], f"{context}.{predicate}")
        mask = values.map(lambda value: not _is_empty_cell(value))
    elif predicate == "is_null":
        _ensure_boolean_predicate(condition[predicate], f"{context}.{predicate}")
        mask = values.map(_is_empty_cell)
    elif predicate == "not_null":
        _ensure_boolean_predicate(condition[predicate], f"{context}.{predicate}")
        mask = values.map(lambda value: not _is_empty_cell(value))
    else:  # pragma: no cover - guarded above
        raise AssertionError(predicate)

    return ~mask if condition[predicate] is False else mask


def _condition_string(condition: Mapping[str, Any], field_name: str, *, context: str) -> str:
    value = condition.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{field_name} must be a non-empty string")
    return value


def _condition_summary(condition: Mapping[str, Any]) -> str:
    column = str(condition.get("column", ""))
    predicate = next((key for key in condition if key in _CONDITION_PREDICATES), "")
    return f"{column} {predicate} {condition.get(predicate)!r}".strip()


def _skipped_rule(
    rule_type: str,
    rule: Mapping[str, Any],
    reason: str,
) -> ReferenceFinding:
    frame = str(rule.get("frame") or "")
    columns = _raw_columns(rule.get("columns"))
    return ReferenceFinding(
        rule_type=rule_type,
        frame=frame,
        columns=columns,
        row_index=None,
        value=None,
        severity="skipped",
        message=f"Validation skipped: {reason}.",
    )


def _duplicate_findings(
    rule_type: str,
    *,
    frame_name: str,
    frame: pd.DataFrame,
    columns: list[str],
    severity: str,
    message: str,
) -> list[ReferenceFinding]:
    row_keys = _row_keys(frame, columns)
    counts = Counter(_key_token(key) for _, key in row_keys)
    return [
        ReferenceFinding(
            rule_type=rule_type,
            frame=frame_name,
            columns=columns,
            row_index=row_index,
            value=key,
            severity=severity,
            message=message,
        )
        for row_index, key in row_keys
        if counts[_key_token(key)] > 1
    ]


def _schema_finding(
    rule_type: str,
    frame_name: str,
    columns: list[str],
    missing_columns: list[str],
    severity: str,
    *,
    target_frame: str = "",
    target_columns: list[str] | None = None,
) -> ReferenceFinding:
    if missing_columns:
        message = f"Configured column(s) are missing: {missing_columns!r}."
    else:
        message = f"Configured frame {frame_name!r} is missing or is not a DataFrame."
    return ReferenceFinding(
        rule_type=rule_type,
        frame=frame_name,
        columns=columns,
        row_index=None,
        value=None,
        target_frame=target_frame,
        target_columns=target_columns,
        severity=severity,
        message=message,
    )


def _frame_and_columns(rule: Mapping[str, Any]) -> tuple[str, list[str]]:
    return _string_field(rule, "frame"), _string_list(rule.get("columns"), "columns")


def _optional_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame | None:
    frame = frames.get(name)
    if not isinstance(frame, pd.DataFrame):
        return None
    if isinstance(frame.columns, pd.MultiIndex) or any(isinstance(col, tuple) for col in frame.columns):
        raise ValueError(f"Frame {name!r} must have flat columns")
    if len(set(frame.columns)) != len(frame.columns):
        raise ValueError(f"Frame {name!r} must not contain duplicate columns")
    return frame


def _missing_rule_columns(frame: pd.DataFrame | None, columns: list[str]) -> list[str]:
    if frame is None:
        return []
    return [column for column in columns if column not in frame.columns]


def _row_keys(frame: pd.DataFrame, columns: list[str]) -> list[tuple[Any, tuple[Any, ...]]]:
    return [
        (row_index, tuple(_plain_value(row[column]) for column in columns))
        for row_index, row in frame.loc[:, columns].iterrows()
    ]


def _valid_mode(mode: str) -> str:
    if mode not in _VALID_MODES:
        raise ValueError(f"validate_references mode must be one of {sorted(_VALID_MODES)!r}")
    return mode


def _valid_findings_name(findings: str) -> str:
    if not isinstance(findings, str) or not findings.strip():
        raise ValueError("validate_references findings must be a non-empty frame name")
    return findings


def _string_field(rule: Mapping[str, Any], field_name: str) -> str:
    value = rule.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"validate_references rule field {field_name!r} must be a non-empty string")
    return value


def _string_list(value: Any, field_name: str) -> list[str]:
    if isinstance(value, str):
        result = [value]
    elif isinstance(value, Iterable):
        result = list(value)
    else:
        raise ValueError(f"validate_references rule field {field_name!r} must be a list")
    if not result:
        raise ValueError(f"validate_references rule field {field_name!r} must not be empty")
    invalid = [item for item in result if not isinstance(item, str) or not item.strip()]
    if invalid:
        raise ValueError(
            f"validate_references rule field {field_name!r} must contain non-empty strings: "
            f"{invalid!r}"
        )
    duplicates = [item for item in dict.fromkeys(item for item in result if result.count(item) > 1)]
    if duplicates:
        raise ValueError(
            f"validate_references rule field {field_name!r} must not contain duplicates: "
            f"{duplicates!r}"
        )
    return result


def _raw_columns(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value]
    return []


def _plain_value(value: Any) -> Any:
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (AttributeError, TypeError, ValueError):
            pass
    if _is_empty_cell(value):
        return None
    return value


def _is_empty_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _key_token(key: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(_format_scalar(value) for value in key)


def _format_columns(columns: list[str]) -> str:
    return ", ".join(columns)


def _format_value(value: tuple[Any, ...]) -> str:
    if len(value) == 1:
        return _format_scalar(value[0])
    return json.dumps([_format_scalar(part) for part in value], ensure_ascii=False)


def _format_scalar(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _ensure_boolean_predicate(value: Any, field_name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be true or false")


def _failure_findings(findings: list[ReferenceFinding]) -> list[ReferenceFinding]:
    return [finding for finding in findings if finding.severity != "skipped"]


def _failure_message(findings: list[ReferenceFinding], *, name: str | None) -> str:
    heading = name or "validate_references"
    lines = [_finding_line(finding) for finding in findings[:10]]
    suffix = "" if len(findings) <= 10 else f"\n  ... {len(findings) - 10} more finding(s)"
    return (
        f"{heading} failed with {len(findings)} reference validation finding(s):\n"
        + "\n".join(f"  - {line}" for line in lines)
        + suffix
    )


def _finding_line(finding: ReferenceFinding) -> str:
    record = finding.to_record()
    target = (
        f" -> {record['target_frame']}({record['target_columns']})"
        if record["target_frame"]
        else ""
    )
    row = f" row {record['row_index']}" if record["row_index"] != "" else ""
    value = f" value={record['value']!r}" if record["value"] != "" else ""
    return (
        f"{record['rule_type']} {record['frame']}({record['columns']})"
        f"{target}{row}{value}: {record['message']}"
    )
