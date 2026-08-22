"""Helper-column removal driven by truthful transient FK provenance.

The ``remove_fk_helpers`` primitive removes helper columns recorded by
truthful, current transient provenance under
``_meta.derived.sheets.*.helper_columns``. The durable v2 relation policy at
``_meta.helper_policies.fk`` names what FK *would* request, not what FK
*currently produced* on this frame, so it is never an independent source of
deletion candidates -- it is consulted only to answer the unrelated
precondition question "was FK helper policy configured at all" (the
``missing_fk_policy_error`` check below). See
``docs/warm_storage/global_reviews/
derived_artifact_deletion_authority_design_2026-08-21.adoc`` Section F/G.
Missing both provenance and durable policy for the whole run is a clear
error -- the prefix fallback that previously hid such failures has been
removed by ``FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5``.
"""
from __future__ import annotations

import logging
from typing import Any

from ....frame_keys import copy_reserved_frames, iter_data_frames

from .policy import (
    derived_helper_columns_by_sheet,
    missing_fk_policy_error,
    resolve_v2_fk_relations,
    source_frame_has_column,
)
from .provenance import _clean_helper_provenance, _visible_label

Frames = dict[str, Any]

log = logging.getLogger("sheets.fk_helpers")


def drop_helpers(frames: Frames, *, prefix: str = "_") -> Frames:
    """Remove materialized helper columns using truthful transient provenance.

    ``prefix`` is retained as a step-binding parameter so the YAML surface
    keeps compatibility, but it is not used to compute deletion candidates.
    Cleanup follows derived provenance per sheet only. The durable v2
    relation policy is consulted solely for the "was FK policy configured at
    all" precondition -- a relation naming a helper for a sheet without
    transient provenance is left in place, not deleted (accepted design
    Section F: durable policy never independently authorizes deletion).
    Missing both provenance and durable policy raises a clear error.
    """
    del prefix  # retained for backwards-compatible step binding only

    relations = resolve_v2_fk_relations(frames)
    provenance_by_sheet = derived_helper_columns_by_sheet(frames)

    if relations is None and not provenance_by_sheet:
        raise missing_fk_policy_error("remove_fk_helpers")

    columns_to_drop = _columns_to_drop_by_sheet(provenance_by_sheet)
    _log_durable_policy_only_survivors(
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
    provenance_by_sheet: dict[str, list[dict[str, Any]]],
) -> dict[str, set[str]]:
    """Deletion candidates come only from truthful transient FK provenance.

    Durable v2 relation policy names what FK would request, not what FK
    currently produced, and is therefore never a source of physical
    deletion candidates (accepted design Section F/G).
    """
    return {
        sheet: {str(entry["column"]) for entry in entries if entry.get("column")}
        for sheet, entries in provenance_by_sheet.items()
    }


def _log_durable_policy_only_survivors(
    frames: Frames,
    *,
    relations: list[dict[str, Any]],
    provenance_by_sheet: dict[str, list[dict[str, Any]]],
) -> None:
    """Non-raising diagnostic: durable policy names a column, but with no
    truthful transient provenance to authorize deletion it is left in place.

    Only fires when the named column is actually physically present --
    a relation for a sheet that never materialized (or no longer carries)
    the column is not a real survivor worth logging.
    """
    if not relations:
        return
    frame_by_name = dict(iter_data_frames(frames))
    for relation in relations:
        source_frame = str(relation.get("source_frame", ""))
        if not source_frame or source_frame in provenance_by_sheet:
            # Provenance is authoritative for sheets that have it.
            continue
        df = frame_by_name.get(source_frame)
        if df is None:
            continue
        for entry in relation.get("helper_columns") or []:
            column = str(entry.get("column", ""))
            if column and source_frame_has_column(df, column):
                log.warning(
                    "drop_helpers: leaving %r on frame %r in place -- durable "
                    "FK policy names it but no truthful transient provenance "
                    "authorizes deletion",
                    column,
                    source_frame,
                )
