from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any


FRAME_LIFECYCLE_KEY = "frame_lifecycle"
WORKBOOK_VIEW_KEY = "workbook_view"


def frame_lifecycle(meta: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(meta, Mapping):
        return {}
    value = meta.get(FRAME_LIFECYCLE_KEY)
    return value if isinstance(value, Mapping) else {}


def write_frame_lifecycle(
    frames: MutableMapping[str, Any],
    frame: str,
    *,
    role: str,
    canonical: bool,
    editable: bool | str,
    render: str,
    derived_from: Iterable[str] | None = None,
    superseded_by: Iterable[str] | None = None,
    produced_by: Mapping[str, Any] | None = None,
    consistency_policy: Mapping[str, Any] | None = None,
    preserve_existing_canonical: bool = True,
) -> None:
    meta = _meta_dict(frames)
    lifecycle = dict(meta.get(FRAME_LIFECYCLE_KEY) or {})
    existing = dict(lifecycle.get(frame) or {})

    if preserve_existing_canonical and existing.get("canonical") is True and not canonical:
        role = str(existing.get("role") or role)
        canonical = True
        editable = existing.get("editable", editable)
        render = str(existing.get("render") or render)

    entry = dict(existing)
    entry.update(
        {
            "role": role,
            "canonical": canonical,
            "editable": editable,
            "render": render,
        }
    )
    if derived_from is not None:
        entry["derived_from"] = _unique_strings(derived_from)
    if superseded_by is not None:
        entry["superseded_by"] = _unique_strings(superseded_by)
    if produced_by is not None:
        entry["produced_by"] = dict(produced_by)
    if consistency_policy is not None:
        entry["consistency_policy"] = dict(consistency_policy)

    lifecycle[frame] = entry
    meta[FRAME_LIFECYCLE_KEY] = lifecycle
    frames["_meta"] = meta


def mark_source_if_unclassified(
    frames: MutableMapping[str, Any],
    frame: str,
    *,
    role: str = "canonical_source",
    canonical: bool = True,
    editable: bool | str = False,
    render: str = "visible_by_default",
) -> None:
    meta = _meta_dict(frames)
    lifecycle = frame_lifecycle(meta)
    if frame in lifecycle:
        return
    write_frame_lifecycle(
        frames,
        frame,
        role=role,
        canonical=canonical,
        editable=editable,
        render=render,
        derived_from=[],
    )


def _meta_dict(frames: MutableMapping[str, Any]) -> dict[str, Any]:
    existing = frames.get("_meta")
    return dict(existing) if isinstance(existing, Mapping) else {}


def _unique_strings(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))
