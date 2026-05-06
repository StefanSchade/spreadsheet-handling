from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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
    if isinstance(include_roles, list) and include_roles and role not in set(map(str, include_roles)):
        return False

    omit_roles = view.get("omit_roles")
    configured_omit_roles = (
        set(map(str, omit_roles))
        if isinstance(omit_roles, list)
        else set(DEFAULT_OMIT_ROLES)
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
