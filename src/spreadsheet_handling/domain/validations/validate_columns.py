from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.column_roles import (
    ROLE_NAMES,
    resolve_column_roles,
)

Frames = dict[str, Any]


def add_validations(frames: Frames, *, rules: list[dict[str, Any]]) -> Frames:
    # get or create meta on either frames.meta (attr) or frames["_meta"] (dict key)
    if hasattr(frames, "meta"):
        meta = frames.meta or {}
        where = "attr"
    elif isinstance(frames, dict):
        meta = frames.get("_meta") or {}
        frames["_meta"] = meta
        where = "key"
    else:
        # last resort: create a temporary sidecar
        meta = {}
        where = "temp"

    constraints = list(meta.get("constraints") or [])
    for raw_rule in rules:
        target = _normalize_target(raw_rule)
        rule = (raw_rule.get("rule") or {})
        rule_type = rule.get("type")
        if rule_type == "in_list":
            constraint_rule = {
                "type": "in_list",
                "values": list(rule.get("values") or []),
            }
        elif rule_type == "from_legend":
            constraint_rule = {
                "type": "from_legend",
                "legend": rule.get("legend"),
            }
            if "include_empty" in rule:
                constraint_rule["include_empty"] = bool(rule.get("include_empty"))
        else:
            raise ValueError(f"unsupported rule.type={rule.get('type')}")
        for column in _target_columns(frames, target):
            constraint = {
                "sheet": target["sheet"],
                "column": column,
                "rule": constraint_rule,
                "on_violation": raw_rule.get("on_violation", "error"),
            }
            if target.get("area") is not None:
                constraint["area"] = target.get("area")
            constraints.append(constraint)

    meta["constraints"] = constraints

    if where == "attr":
        frames.meta = meta
    elif where == "key":
        frames["_meta"] = meta

    return frames


def _normalize_target(rule: Mapping[str, Any]) -> dict[str, Any]:
    nested = rule.get("target") or {}
    if nested and not isinstance(nested, Mapping):
        raise ValueError("add_validations target must be a mapping")

    target = {}
    for key in ("sheet", "frame", "column", "columns", "roles", "area"):
        if key in nested:
            target[key] = nested[key]
        elif key in rule:
            target[key] = rule[key]

    if not target.get("sheet"):
        raise ValueError("add_validations target requires 'sheet'")
    target["sheet"] = str(target["sheet"])
    return target


def _target_columns(frames: Frames, target: Mapping[str, Any]) -> list[str | None]:
    has_roles = "roles" in target and target.get("roles") is not None
    has_column = "column" in target and target.get("column") is not None
    has_columns = "columns" in target and target.get("columns") is not None

    if has_roles:
        if has_column or has_columns:
            raise ValueError(
                "add_validations target must not combine 'roles' with "
                "explicit 'column' or 'columns'"
            )
        return _role_target_columns(frames, target)

    if has_column and has_columns:
        raise ValueError(
            "add_validations target must not combine 'column' and 'columns'"
        )
    if has_columns:
        return _string_list(target.get("columns"), "columns")
    return [None if target.get("column") is None else str(target.get("column"))]


def _role_target_columns(frames: Frames, target: Mapping[str, Any]) -> list[str | None]:
    roles = _string_list(target.get("roles"), "roles")
    unknown = [role for role in roles if role not in ROLE_NAMES]
    if unknown:
        raise ValueError(
            f"add_validations target contains unknown role(s) {unknown!r}; "
            f"expected names from {sorted(ROLE_NAMES)!r}"
        )

    frame = _target_frame(frames, target)
    column_roles = resolve_column_roles(frames, frame=frame)

    columns: list[str | None] = []
    seen: set[str] = set()
    for role in roles:
        for column in column_roles.columns_for(role):
            if column in seen:
                continue
            seen.add(column)
            columns.append(column)
    return columns


def _target_frame(frames: Frames, target: Mapping[str, Any]) -> str:
    explicit = target.get("frame")
    if explicit is not None:
        frame = str(explicit)
        if frame:
            return frame

    sheet = str(target["sheet"])
    mapped = _frame_for_sheet_from_workbook_view(frames.get("_meta"), sheet=sheet)
    if mapped:
        return mapped

    if isinstance(frames.get(sheet), pd.DataFrame):
        return sheet

    raise ValueError(
        "add_validations target with 'roles' requires 'frame' or a "
        f"workbook_view sheet mapping for sheet {sheet!r}"
    )


def _frame_for_sheet_from_workbook_view(meta: Any, *, sheet: str) -> str | None:
    if not isinstance(meta, Mapping):
        return None
    workbook_view = meta.get("workbook_view")
    if not isinstance(workbook_view, Mapping):
        return None
    sheets = workbook_view.get("sheets")
    if not isinstance(sheets, Sequence) or isinstance(sheets, (str, bytes)):
        return None
    for entry in sheets:
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("sheet")) != sheet:
            continue
        frame = entry.get("frame")
        if frame is None:
            continue
        return str(frame)
    return None


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(
            f"add_validations target field {field_name!r} must be a non-empty list"
        )
    result: list[str] = []
    invalid: list[Any] = []
    for item in value:
        text = str(item).strip() if item is not None else ""
        if not text:
            invalid.append(item)
            continue
        result.append(text)
    if invalid or not result:
        raise ValueError(
            f"add_validations target field {field_name!r} must contain "
            f"non-empty role/column names: {list(value)!r}"
        )
    return result
