"""Declarative workbook view configuration and readback mapping helpers."""

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
WORKBOOK_VIEW_SHEET_MAPPINGS_KEY = "sheet_mappings"

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


@dataclass(frozen=True)
class WorkbookViewSheetMapping:
    visible_sheet: str
    logical_frame: str
    canonical_frame: str | None = None


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
        WORKBOOK_VIEW_SHEET_MAPPINGS_KEY: _sheet_mappings(out, normalized),
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
    seen_frames: set[str] = set()
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
        if frame in seen_frames:
            raise ValueError(f"Duplicate workbook view frame {frame!r}")
        seen_frames.add(frame)

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


def resolve_workbook_view_sheet_mappings(
    meta: Mapping[str, Any] | None,
    *,
    visible_sheets: Iterable[str] | Mapping[str, Any] | None = None,
    logical_frames: Iterable[str] | None = None,
) -> dict[str, WorkbookViewSheetMapping]:
    """Resolve persisted visible-sheet -> logical-frame mappings from workbook meta."""
    view = _workbook_view_mapping(meta)
    raw_mappings = view.get(WORKBOOK_VIEW_SHEET_MAPPINGS_KEY)
    if raw_mappings is None:
        raise ValueError(
            f"_meta.workbook_view.{WORKBOOK_VIEW_SHEET_MAPPINGS_KEY} is required for workbook "
            "view readback"
        )
    if not isinstance(raw_mappings, list):
        raise ValueError(
            f"_meta.workbook_view.{WORKBOOK_VIEW_SHEET_MAPPINGS_KEY} must be a list"
        )

    mappings: dict[str, WorkbookViewSheetMapping] = {}
    seen_frames: set[str] = set()
    for index, raw_entry in enumerate(raw_mappings, start=1):
        if not isinstance(raw_entry, Mapping):
            raise ValueError(
                f"_meta.workbook_view.{WORKBOOK_VIEW_SHEET_MAPPINGS_KEY}[{index}] "
                f"must be a mapping, got {type(raw_entry).__name__}"
            )
        visible_sheet = _non_empty_string(
            raw_entry.get("sheet"),
            f"_meta.workbook_view.{WORKBOOK_VIEW_SHEET_MAPPINGS_KEY}[{index}].sheet",
        )
        logical_frame = _non_empty_string(
            raw_entry.get("frame"),
            f"_meta.workbook_view.{WORKBOOK_VIEW_SHEET_MAPPINGS_KEY}[{index}].frame",
        )
        canonical_frame = _optional_non_empty_string(
            raw_entry.get("canonical_frame"),
            f"_meta.workbook_view.{WORKBOOK_VIEW_SHEET_MAPPINGS_KEY}[{index}].canonical_frame",
        )
        if visible_sheet in mappings:
            raise ValueError(
                f"Duplicate visible sheet mapping for {visible_sheet!r} in "
                f"_meta.workbook_view.{WORKBOOK_VIEW_SHEET_MAPPINGS_KEY}"
            )
        if logical_frame in seen_frames:
            raise ValueError(
                f"Duplicate logical frame mapping for {logical_frame!r} in "
                f"_meta.workbook_view.{WORKBOOK_VIEW_SHEET_MAPPINGS_KEY}"
            )
        seen_frames.add(logical_frame)
        mappings[visible_sheet] = WorkbookViewSheetMapping(
            visible_sheet=visible_sheet,
            logical_frame=logical_frame,
            canonical_frame=canonical_frame,
        )

    visible_sheet_names = _normalize_visible_sheet_names(visible_sheets)
    if visible_sheet_names is not None:
        for sheet_name in visible_sheet_names:
            if sheet_name not in mappings:
                raise ValueError(
                    f"Visible sheet {sheet_name!r} is not declared in "
                    f"_meta.workbook_view.{WORKBOOK_VIEW_SHEET_MAPPINGS_KEY}"
                )
        missing = [sheet_name for sheet_name in mappings if sheet_name not in visible_sheet_names]
        if missing:
            raise ValueError(
                "Workbook is missing required visible sheet(s) declared in "
                f"_meta.workbook_view.{WORKBOOK_VIEW_SHEET_MAPPINGS_KEY}: {missing!r}"
            )

    logical_frame_names = set(map(str, logical_frames)) if logical_frames is not None else None
    if logical_frame_names is not None:
        for mapping in mappings.values():
            if mapping.logical_frame not in logical_frame_names:
                raise ValueError(
                    f"Workbook view mapping references unknown logical frame "
                    f"{mapping.logical_frame!r}"
                )
            if (
                mapping.canonical_frame is not None
                and mapping.canonical_frame not in logical_frame_names
            ):
                raise ValueError(
                    f"Workbook view mapping references unknown canonical frame "
                    f"{mapping.canonical_frame!r}"
                )

    return mappings


def _sheet_mappings(
    frames: Mapping[str, Any],
    sheets: list[_SheetSpec],
) -> list[dict[str, str]]:
    lifecycle = frame_lifecycle(frames.get("_meta"))
    mappings: list[dict[str, str]] = []
    for sheet in sheets:
        mapping = {
            "sheet": sheet.sheet,
            "frame": sheet.frame,
        }
        canonical_frame = _explicit_canonical_frame(sheet.frame, lifecycle)
        if canonical_frame is not None:
            mapping["canonical_frame"] = canonical_frame
        mappings.append(mapping)
    return mappings


def _explicit_canonical_frame(
    frame: str,
    lifecycle: Mapping[str, Any],
) -> str | None:
    entry = lifecycle.get(frame)
    if not isinstance(entry, Mapping):
        return None
    if entry.get("canonical") is True:
        return frame

    derived_from = entry.get("derived_from")
    if not isinstance(derived_from, list) or len(derived_from) != 1:
        return None

    canonical_frame = derived_from[0]
    source_entry = lifecycle.get(canonical_frame)
    if isinstance(source_entry, Mapping) and source_entry.get("canonical") is True:
        return str(canonical_frame)
    return None


def _workbook_view_mapping(meta: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(meta, Mapping):
        raise ValueError("_meta.workbook_view is required for workbook view readback")
    view = meta.get("workbook_view")
    if not isinstance(view, Mapping):
        raise ValueError("_meta.workbook_view must be a mapping for workbook view readback")
    return view


def _normalize_visible_sheet_names(
    visible_sheets: Iterable[str] | Mapping[str, Any] | None,
) -> set[str] | None:
    if visible_sheets is None:
        return None
    if isinstance(visible_sheets, Mapping):
        return {
            str(name)
            for name, value in visible_sheets.items()
            if str(name) != "_meta" and isinstance(value, pd.DataFrame)
        }
    if isinstance(visible_sheets, (str, bytes)):
        raise TypeError("visible_sheets must be an iterable of sheet names, not a scalar")
    return {str(name) for name in visible_sheets}


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


def _optional_non_empty_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field_name)


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
