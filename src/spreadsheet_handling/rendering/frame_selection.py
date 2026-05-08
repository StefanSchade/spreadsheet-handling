from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.rendering.formulas import LookupFormulaSpec, lookup_formula

RESERVED_FRAME_KEYS = {"_meta"}
DEFAULT_OMIT_ROLES = {"intermediate", "redundant", "system"}
DEFAULT_INCLUDE_ROLES = {
    "canonical_source",
    "source",
    "editable_projection",
    "readonly_projection",
    "diagnostic",
    "unknown",
}


def select_render_frames(
    frames: Mapping[str, Any],
    meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    view = _view_policy(meta)
    if view is None:
        return dict(frames)

    explicit_sheets = _configured_sheets(view)
    if explicit_sheets is not None:
        return _select_configured_sheets(frames, explicit_sheets)

    lifecycle = _lifecycle(meta)
    selected: dict[str, Any] = {}
    for raw_name, value in frames.items():
        name = str(raw_name)
        if name in RESERVED_FRAME_KEYS:
            selected[raw_name] = value
            continue
        if _should_render_frame(name, lifecycle.get(name), view):
            selected[raw_name] = value
    return selected


def _configured_sheets(view: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    sheets = view.get("sheets")
    if sheets is None:
        return None
    if not isinstance(sheets, list):
        raise TypeError("workbook_view.sheets must be a list")
    entries: list[Mapping[str, Any]] = []
    for index, entry in enumerate(sheets, start=1):
        if not isinstance(entry, Mapping):
            raise TypeError(f"workbook_view.sheets entry {index} must be a mapping")
        entries.append(entry)
    return entries


def _select_configured_sheets(
    frames: Mapping[str, Any],
    sheets: list[Mapping[str, Any]],
) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    seen_sheets: set[str] = set()
    frame_to_sheet: dict[str, str] = {}
    for index, entry in enumerate(sheets, start=1):
        frame = _non_empty_string(entry.get("frame"), f"workbook_view.sheets[{index}].frame")
        if frame in RESERVED_FRAME_KEYS:
            raise ValueError(
                f"workbook_view.sheets entry {index} references reserved frame {frame!r}"
            )
        if frame not in frames:
            raise KeyError(f"workbook_view.sheets entry {index} references missing frame {frame!r}")
        value = frames[frame]
        if not isinstance(value, pd.DataFrame):
            raise TypeError(
                f"workbook_view.sheets entry {index} frame {frame!r} must be a DataFrame"
            )

        sheet = _non_empty_string(
            entry.get("sheet") or frame,
            f"workbook_view.sheets[{index}].sheet",
        )
        if sheet in RESERVED_FRAME_KEYS:
            raise ValueError(
                f"workbook_view.sheets entry {index} uses reserved sheet name {sheet!r}"
            )
        if sheet in seen_sheets:
            raise ValueError(f"Duplicate workbook view sheet name {sheet!r}")
        seen_sheets.add(sheet)
        selected[sheet] = value
        if frame != sheet:
            frame_to_sheet[frame] = sheet

    if frame_to_sheet:
        _resolve_formula_sheet_names(selected, frame_to_sheet)

    if "_meta" in frames:
        selected["_meta"] = frames["_meta"]
    return selected


def _view_policy(meta: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(meta, Mapping):
        return None
    view = meta.get("workbook_view")
    return view if isinstance(view, Mapping) else None


def _lifecycle(meta: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(meta, Mapping):
        return {}
    lifecycle = meta.get("frame_lifecycle")
    return lifecycle if isinstance(lifecycle, Mapping) else {}


def _should_render_frame(
    name: str,
    entry: Any,
    view: Mapping[str, Any],
) -> bool:
    if not isinstance(entry, Mapping):
        return _unknown_frame_decision(name, view)

    render = str(entry.get("render") or "unknown")
    role = str(entry.get("role") or "unknown")
    include_debug = bool(view.get("include_debug_frames")) or str(view.get("mode")) in {
        "debug",
        "full",
    }

    if render == "never":
        return False
    if render == "debug_only":
        return include_debug

    include_roles = view.get("include_roles")
    if (
        isinstance(include_roles, list)
        and include_roles
        and role not in set(map(str, include_roles))
    ):
        return False

    omit_roles = view.get("omit_roles")
    configured_omit_roles = (
        set(map(str, omit_roles)) if isinstance(omit_roles, list) else set(DEFAULT_OMIT_ROLES)
    )
    drop_redundant = bool(view.get("drop_redundant_data")) or str(view.get("mode")) == "editable"

    if drop_redundant and role in configured_omit_roles:
        return False
    if drop_redundant and render == "omit_by_default":
        return bool(view.get("include_omit_by_default"))
    if role == "unknown":
        return _unknown_frame_decision(name, view)
    if role not in DEFAULT_INCLUDE_ROLES and render == "unknown":
        return _unknown_frame_decision(name, view)
    return True


def _unknown_frame_decision(name: str, view: Mapping[str, Any]) -> bool:
    policy = str(view.get("unknown_frame_policy") or "visible")
    if policy == "visible":
        return True
    if policy == "omit":
        return False
    if policy == "fail":
        raise ValueError(f"Frame {name!r} has no frame_lifecycle entry")
    raise ValueError(f"Unsupported unknown_frame_policy {policy!r}")


def _non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _resolve_formula_sheet_names(
    selected: dict[str, Any],
    frame_to_sheet: dict[str, str],
) -> None:
    """Rewrite LookupFormulaSpec.lookup_sheet from frame name to physical sheet name."""
    for sheet_name, value in selected.items():
        if not isinstance(value, pd.DataFrame):
            continue
        for col in value.columns:
            series = value[col]
            if series.empty:
                continue
            first = series.iloc[0]
            if not isinstance(first, LookupFormulaSpec):
                continue
            if first.lookup_sheet not in frame_to_sheet:
                continue
            new_sheet = frame_to_sheet[first.lookup_sheet]
            value[col] = series.apply(
                lambda cell, ns=new_sheet: lookup_formula(
                    source_key_column=cell.source_key_column,
                    lookup_sheet=ns,
                    lookup_key_column=cell.lookup_key_column,
                    lookup_value_column=cell.lookup_value_column,
                    missing=cell.missing,
                )
                if isinstance(cell, LookupFormulaSpec) and cell.lookup_sheet in frame_to_sheet
                else cell,
            )
