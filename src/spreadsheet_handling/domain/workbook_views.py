"""Declarative workbook view configuration."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.frame_lifecycle import (
    frame_lifecycle,
    write_frame_lifecycle,
)

Frames = dict[str, Any]

_RESERVED_FRAME_KEYS = {"_meta"}
_ALLOWED_SHEET_KEYS = {
    "frame",
    "sheet",
    "editable_columns",
    "helper_columns",
    "lifecycle",
    "options",
    "protection",
    "role",
    "canonical",
    "editable",
    "render",
}
_TRANSFORMATION_KEYS = {
    "columns",
    "where",
    "sort_by",
    "rename",
    "join",
    "left",
    "right",
    "pivot",
    "aggregation",
}


@dataclass(frozen=True)
class _SheetSpec:
    frame: str
    sheet: str
    editable_columns: list[str] | None
    helper_columns: list[str] | None
    protection: Mapping[str, Any] | None
    lifecycle: Mapping[str, Any]
    options: Mapping[str, Any] | None


def configure_workbook_view(
    frames: Mapping[str, Any],
    *,
    sheets: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    mode: str = "editable",
    drop_redundant_data: bool = True,
    unknown_frame_policy: str = "fail",
    include_debug_frames: bool = False,
    include_omit_by_default: bool = False,
    include_roles: Iterable[str] | None = None,
    omit_roles: Iterable[str] | None = None,
    name: str | None = None,
) -> Frames:
    """Write workbook view selection, ordering, sheet names, and lifecycle metadata."""
    normalized = _normalize_sheet_specs(sheets, frames)

    out: dict[str, Any] = dict(frames)
    out["_meta"] = dict(frames.get("_meta") or {})
    for sheet in normalized:
        _write_sheet_lifecycle(out, sheet)

    meta = dict(out.get("_meta") or {})
    view: dict[str, Any] = {
        "mode": _non_empty_string(mode, "mode"),
        "drop_redundant_data": bool(drop_redundant_data),
        "unknown_frame_policy": _non_empty_string(unknown_frame_policy, "unknown_frame_policy"),
        "sheets": [
            {
                "frame": sheet.frame,
                "sheet": sheet.sheet,
                "order": index,
            }
            for index, sheet in enumerate(normalized)
        ],
    }
    if include_debug_frames:
        view["include_debug_frames"] = True
    if include_omit_by_default:
        view["include_omit_by_default"] = True
    if include_roles is not None:
        view["include_roles"] = _string_list(include_roles, "include_roles")
    if omit_roles is not None:
        view["omit_roles"] = _string_list(omit_roles, "omit_roles")
    if name is not None:
        view["name"] = _non_empty_string(name, "name")

    meta["workbook_view"] = view
    _merge_sheet_options(meta, normalized)
    out["_meta"] = meta
    return out


def _normalize_sheet_specs(
    sheets: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    frames: Mapping[str, Any],
) -> list[_SheetSpec]:
    raw_specs = _raw_sheet_specs(sheets)
    if not raw_specs:
        raise ValueError("sheets must not be empty")

    normalized: list[_SheetSpec] = []
    seen_sheets: set[str] = set()
    for index, raw in enumerate(raw_specs, start=1):
        if not isinstance(raw, Mapping):
            raise TypeError(f"sheets entry {index} must be a mapping")
        _reject_transform_keys(raw, index=index)
        unsupported = sorted(set(raw) - _ALLOWED_SHEET_KEYS)
        if unsupported:
            raise ValueError(f"sheets entry {index} contains unsupported key(s): {unsupported!r}")

        frame = _non_empty_string(raw.get("frame"), f"sheets[{index}].frame")
        if frame in _RESERVED_FRAME_KEYS:
            raise ValueError(f"sheets entry {index} references reserved frame {frame!r}")
        if frame not in frames:
            raise KeyError(f"sheets entry {index} references missing frame {frame!r}")
        if not isinstance(frames[frame], pd.DataFrame):
            raise TypeError(f"sheets entry {index} frame {frame!r} must be a pandas DataFrame")

        sheet = _non_empty_string(raw.get("sheet") or frame, f"sheets[{index}].sheet")
        if sheet in _RESERVED_FRAME_KEYS:
            raise ValueError(f"sheets entry {index} uses reserved sheet name {sheet!r}")
        if sheet in seen_sheets:
            raise ValueError(f"Duplicate workbook view sheet name {sheet!r}")
        seen_sheets.add(sheet)

        lifecycle = _lifecycle_mapping(raw, index=index)
        helper_columns = _optional_string_list(
            raw.get("helper_columns"),
            f"sheets[{index}].helper_columns",
        )
        editable_columns = _optional_string_list(
            raw.get("editable_columns"),
            f"sheets[{index}].editable_columns",
        )
        protection = raw.get("protection")
        if protection is not None and not isinstance(protection, Mapping):
            raise TypeError(f"sheets entry {index} protection must be a mapping")
        options = raw.get("options")
        if options is not None and not isinstance(options, Mapping):
            raise TypeError(f"sheets entry {index} options must be a mapping")
        normalized.append(
            _SheetSpec(
                frame=frame,
                sheet=sheet,
                editable_columns=editable_columns,
                helper_columns=helper_columns,
                protection=protection,
                lifecycle=lifecycle,
                options=options,
            )
        )
    return normalized


def _raw_sheet_specs(sheets: Iterable[Mapping[str, Any]] | Mapping[str, Any]) -> list[Any]:
    if isinstance(sheets, Mapping):
        raw: list[Any] = []
        for frame_name, value in sheets.items():
            if isinstance(value, str):
                raw.append({"frame": frame_name, "sheet": value})
            elif isinstance(value, Mapping):
                raw.append({"frame": frame_name, **dict(value)})
            else:
                raise TypeError(
                    "sheets mapping values must be sheet-name strings or sheet spec mappings"
                )
        return raw
    if isinstance(sheets, (str, bytes)):
        raise TypeError("sheets must be a list or mapping, not a scalar")
    return list(sheets)


def _reject_transform_keys(raw: Mapping[str, Any], *, index: int) -> None:
    blocked = sorted(set(raw) & _TRANSFORMATION_KEYS)
    if blocked:
        raise ValueError(
            f"sheets entry {index} contains transformation key(s) {blocked!r}; "
            "workbook views only select, name, order, and annotate already prepared frames"
        )


def _lifecycle_mapping(raw: Mapping[str, Any], *, index: int) -> Mapping[str, Any]:
    lifecycle = raw.get("lifecycle")
    if lifecycle is None:
        lifecycle_map: dict[str, Any] = {}
    elif isinstance(lifecycle, Mapping):
        lifecycle_map = dict(lifecycle)
    else:
        raise TypeError(f"sheets entry {index} lifecycle must be a mapping")

    for key in ("role", "canonical", "editable", "render"):
        if key in raw:
            lifecycle_map[key] = raw[key]
    return lifecycle_map


def _write_sheet_lifecycle(out: dict[str, Any], sheet: _SheetSpec) -> None:
    existing = dict(frame_lifecycle(out.get("_meta")).get(sheet.frame) or {})
    lifecycle = dict(sheet.lifecycle)
    role = str(lifecycle.get("role", existing.get("role", "readonly_projection")))
    canonical = bool(lifecycle.get("canonical", existing.get("canonical", False)))
    editable = lifecycle.get("editable", existing.get("editable", False))
    render = str(lifecycle.get("render", existing.get("render", "visible_by_default")))
    consistency_policy = lifecycle.get("consistency_policy", existing.get("consistency_policy"))
    if consistency_policy is not None and not isinstance(consistency_policy, Mapping):
        raise TypeError("lifecycle.consistency_policy must be a mapping")

    write_frame_lifecycle(
        out,
        sheet.frame,
        role=role,
        canonical=canonical,
        editable=editable,
        render=render,
        derived_from=existing.get("derived_from", []),
        superseded_by=existing.get("superseded_by"),
        produced_by=existing.get("produced_by"),
        consistency_policy=consistency_policy,
        preserve_existing_canonical=True,
    )


def _merge_sheet_options(meta: dict[str, Any], sheets: list[_SheetSpec]) -> None:
    configured = dict(meta.get("sheets") or {})
    for sheet in sheets:
        sheet_options = dict(sheet.options or {})
        if sheet.helper_columns is not None:
            existing = sheet_options.get("helper_columns")
            if existing is not None:
                existing_columns = _string_list(
                    existing,
                    f"sheets.{sheet.sheet}.options.helper_columns",
                )
                if existing_columns != sheet.helper_columns:
                    raise ValueError(
                        f"sheets entry for {sheet.sheet!r} defines conflicting "
                        "helper_columns in top-level sheet spec and options"
                    )
            sheet_options["helper_columns"] = sheet.helper_columns
        if sheet.editable_columns is not None:
            protection = dict(sheet_options.get("protection") or sheet.protection or {})
            protection["editable_columns"] = sheet.editable_columns
            sheet_options["protection"] = protection
        elif sheet.protection is not None:
            sheet_options["protection"] = dict(sheet.protection)
        if not sheet_options:
            continue
        configured[sheet.sheet] = {
            **dict(configured.get(sheet.sheet) or {}),
            **sheet_options,
        }
    if configured:
        meta["sheets"] = configured


def _non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _string_list(values: Iterable[str], field_name: str) -> list[str]:
    if isinstance(values, str):
        result = [values]
    else:
        result = list(values)
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    invalid = [value for value in result if not isinstance(value, str) or not value.strip()]
    if invalid:
        raise ValueError(f"{field_name} must contain non-empty strings: {invalid!r}")
    return result


def _optional_string_list(value: Any, field_name: str) -> list[str] | None:
    if value is None:
        return None
    return _string_list(value, field_name)
