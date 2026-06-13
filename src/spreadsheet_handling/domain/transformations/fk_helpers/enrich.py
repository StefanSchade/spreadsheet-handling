"""FK helper enrichment driven by v2 relation policy.

The primitive ``add_fk_helpers`` consumes the v2 relation policy at
``_meta.helper_policies.fk.relations`` (schema_version 2). It does not infer
relation identity from column names; missing policy is reported clearly.

Refactored by ``FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5`` from the
previous convention-driven enrichment path.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ....core.fk import apply_fk_helpers, build_id_value_maps
from ....frame_keys import copy_reserved_frames, iter_data_frames

from .formula_provider import _lookup_formula_provider
from .policy import (
    build_v2_target_registry,
    iter_relation_fk_defs,
    known_data_frame_names,
    missing_fk_policy_error,
    resolve_v2_fk_relations,
    source_frame_has_column,
)
from .provenance import _visible_label, _write_helper_provenance

Frames = dict[str, Any]

_VALUE_HELPER_MODES = {"value", "values"}
_FORMULA_HELPER_MODES = {"formula", "formulas"}


def enrich_helpers(frames: Frames, defaults: dict[str, Any]) -> Frames:
    """Materialize FK helper columns from the v2 relation policy.

    Reads ``_meta.helper_policies.fk.relations`` (schema_version 2) and
    materializes only what policy declares. Raises a clear error when policy
    is absent so the pipeline author runs ``configure_fk_helpers`` or
    ``infer_fk_relations`` first.
    """
    if not bool(defaults.get("detect_fk", True)):
        return frames

    relations = resolve_v2_fk_relations(frames)
    if relations is None:
        raise missing_fk_policy_error("add_fk_helpers")

    levels = int(defaults.get("levels", 3))
    helper_value_mode = _helper_value_mode(defaults)

    # Skip relations whose target frame is not present in the current run.
    # Fresh configuration always validates that the target frame exists
    # (configure_fk_helpers / infer_fk_relations), so an absent target can only
    # come from a durable relation replayed in a run that did not load that
    # frame. Enriching it would crash in build_id_value_maps. Skipping is the
    # safe no-op the functional model prescribes ("target frame essential; no
    # enrichment without it") and is part of the Slice 2 replay-safety control.
    known_names = known_data_frame_names(frames)
    relations = [
        relation
        for relation in relations
        if str(relation.get("target_frame")) in known_names
    ]

    target_registry, fields_by_target_sheet = build_v2_target_registry(relations)

    # Group relations by source frame so a sheet without configured FKs is
    # passed through untouched without inspecting its headers.
    relations_by_source: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        source_frame = str(relation["source_frame"])
        relations_by_source.setdefault(source_frame, []).append(relation)

    helper_value_provider = (
        _lookup_formula_provider(target_registry)
        if helper_value_mode in _FORMULA_HELPER_MODES
        else None
    )

    fk_defs_by_sheet: dict[str, list[Any]] = {}
    for sheet_name, df in iter_data_frames(frames):
        sheet_relations = relations_by_source.get(sheet_name, [])
        sheet_defs: list[Any] = []
        for relation in sheet_relations:
            if not source_frame_has_column(df, str(relation["source_column"])):
                # The configured source frame does not currently carry the
                # FK header. Skip silently: configuration may legitimately
                # cover frame snapshots that have not been built yet.
                continue
            sheet_defs.extend(iter_relation_fk_defs(relation))
        fk_defs_by_sheet[sheet_name] = sheet_defs

    id_maps = build_id_value_maps(
        frames,
        target_registry,
        fields_by_sheet=fields_by_target_sheet,
    )

    out: dict[str, Any] = {}
    copy_reserved_frames(frames, out)
    for sheet_name, df in iter_data_frames(frames):
        sheet_defs = fk_defs_by_sheet[sheet_name]
        if not sheet_defs:
            out[sheet_name] = df
            continue
        enriched = apply_fk_helpers(
            df,
            sheet_defs,
            id_maps,
            levels,
            helper_prefix="_",
            helper_value_provider=helper_value_provider,
        )
        out[sheet_name] = _preserve_source_flatness(df, enriched)

    _write_helper_provenance(out, fk_defs_by_sheet)
    return out


def _columns_are_flat(columns: Any) -> bool:
    return not (
        isinstance(columns, pd.MultiIndex)
        or any(isinstance(column, tuple) for column in columns)
    )


def _preserve_source_flatness(
    source_df: pd.DataFrame,
    enriched_df: pd.DataFrame,
) -> pd.DataFrame:
    """Keep an enriched frame as flat as its source frame was.

    ``apply_fk_helpers`` materializes helper columns as MultiIndex tuples
    padded to ``levels``. When the source frame had flat (single-level)
    columns, that padding turns it into a non-flat frame. A durable FK
    relation (``configure_fk_helpers`` relations are durable as of FK Helper
    Slice 2) that points at a frame the current pipeline does not flatten would
    then crash downstream flat-only steps -- ``join_frames`` and structured
    persistence raise ``Frame ... must have flat columns``. That is exactly the
    Dino-shaped replay failure recorded in
    ``BUG-RUNTIME-META-PERSISTENCE-BOUNDARY-P4A``.

    Collapsing the materialized helper columns back to their first-level label
    keeps a flat frame flat and makes durable relations safe to replay. Helper
    identity is unchanged: the first-level label is the helper column name that
    derived provenance and ``flatten_headers`` already use. Frames that were
    genuinely MultiIndex are left untouched so multi-level layouts are
    preserved.
    """
    if not _columns_are_flat(source_df.columns):
        return enriched_df
    if _columns_are_flat(enriched_df.columns):
        return enriched_df
    flattened = [_visible_label(column) for column in enriched_df.columns]
    result = enriched_df.copy()
    result.columns = flattened
    return result


def _helper_value_mode(defaults: dict[str, Any]) -> str:
    mode = str(defaults.get("helper_value_mode", "values")).lower()
    if mode not in _VALUE_HELPER_MODES and mode not in _FORMULA_HELPER_MODES:
        raise ValueError(
            "helper_value_mode must be one of "
            f"{sorted(_VALUE_HELPER_MODES | _FORMULA_HELPER_MODES)}"
        )
    return mode
