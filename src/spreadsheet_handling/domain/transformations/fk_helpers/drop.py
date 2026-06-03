"""Helper-column removal driven by derived provenance or v2 relation policy.

The ``remove_fk_helpers`` primitive removes helper columns recorded by
derived provenance under ``_meta.derived.sheets.*.helper_columns``. When
provenance is absent on a sheet, the v2 relation policy at
``_meta.helper_policies.fk`` is consulted instead. Missing both is a clear
error -- the prefix fallback that previously hid such failures has been
removed by ``FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5``.
"""
from __future__ import annotations

from typing import Any

from ....frame_keys import copy_reserved_frames, iter_data_frames

from .policy import (
    derived_helper_columns_by_sheet,
    known_data_frame_names,
    missing_fk_policy_error,
    resolve_v2_fk_relations,
)
from .provenance import _clean_helper_provenance, _visible_label

Frames = dict[str, Any]


def drop_helpers(frames: Frames, *, prefix: str = "_") -> Frames:
    """Remove materialized helper columns using provenance or v2 policy.

    ``prefix`` is retained as a step-binding parameter so the YAML surface
    keeps compatibility, but it is no longer used as a normal-path
    fallback. Cleanup follows derived provenance per sheet; when a sheet
    has no provenance, the v2 relation policy supplies the helper column
    names for that source frame. Missing both raises a clear error.
    """
    del prefix  # retained for backwards-compatible step binding only

    relations = resolve_v2_fk_relations(frames)
    provenance_by_sheet = derived_helper_columns_by_sheet(frames)

    if relations is None and not provenance_by_sheet:
        raise missing_fk_policy_error("remove_fk_helpers")

    # Build per-sheet helper column sets:
    # 1) prefer provenance (records the actually-materialized columns), then
    # 2) fall back to v2 policy (the declared shape).
    columns_to_drop = _columns_to_drop_by_sheet(
        frames,
        relations=relations or [],
        provenance_by_sheet=provenance_by_sheet,
    )

    out: dict[str, Any] = {}
    copy_reserved_frames(frames, out)
    meta: dict[str, Any] = dict(out.get("_meta") or {})
    derived_sheets: dict[str, Any] = (meta.get("derived") or {}).get("sheets") or {}

    for sheet, df in iter_data_frames(frames):
        drop_columns = columns_to_drop.get(sheet, set())
        if not drop_columns:
            out[sheet] = df
            continue
        keep = [
            column for column in df.columns
            if _visible_label(column) not in drop_columns
        ]
        out[sheet] = df.loc[:, keep]

    _clean_helper_provenance(out, meta, derived_sheets)
    return out


def _columns_to_drop_by_sheet(
    frames: Frames,
    *,
    relations: list[dict[str, Any]],
    provenance_by_sheet: dict[str, list[dict[str, Any]]],
) -> dict[str, set[str]]:
    columns_to_drop: dict[str, set[str]] = {
        sheet: {str(entry["column"]) for entry in entries if entry.get("column")}
        for sheet, entries in provenance_by_sheet.items()
    }
    if not relations:
        return columns_to_drop

    known_sheets = known_data_frame_names(frames)
    for relation in relations:
        source_frame = str(relation.get("source_frame", ""))
        if source_frame not in known_sheets:
            continue
        if source_frame in provenance_by_sheet:
            # Provenance is authoritative for sheets that have it.
            continue
        helper_columns = relation.get("helper_columns") or []
        bucket = columns_to_drop.setdefault(source_frame, set())
        for entry in helper_columns:
            column = str(entry.get("column", ""))
            if column:
                bucket.add(column)
    return columns_to_drop
