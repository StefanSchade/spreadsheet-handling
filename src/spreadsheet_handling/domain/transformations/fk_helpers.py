"""FK-helper domain transformations: enrichment and cleanup.

Extracted from pipeline.steps (FTR-FK-HELPER-DOMAIN-EXTRACTION).
Pipeline step factories delegate here; this module owns the full
FK-helper lifecycle: resolution, enrichment, provenance, and cleanup.
"""
from __future__ import annotations

from typing import Any

from ...core.fk import (
    build_registry,
    build_id_value_maps,
    detect_fk_columns,
    apply_fk_helpers as _apply_fk_helpers,
)
from ...frame_keys import copy_reserved_frames, iter_data_frames

Frames = dict[str, Any]


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def enrich_helpers(frames: Frames, defaults: dict[str, Any]) -> Frames:
    """Detect FK columns, add helper columns, and write derived provenance.

    This is the domain entry-point called by the ``apply_fks`` pipeline step.
    It orchestrates core.fk utilities and owns the ``_meta`` provenance
    contract for helper columns.
    """
    if not bool(defaults.get("detect_fk", True)):
        return frames

    reg = build_registry(frames, defaults)
    levels = int(defaults.get("levels", 3))
    helper_prefix = str(defaults.get("helper_prefix", "_"))
    fk_defs_by_sheet: dict[str, Any] = {}
    fields_by_target: dict[str, list[str]] = {}

    for sheet_name, df in iter_data_frames(frames):
        fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix, defaults=defaults)
        fk_defs_by_sheet[sheet_name] = fk_defs
        for fk in fk_defs:
            fields_by_target.setdefault(fk.target_sheet_key, [])
            if fk.value_field not in fields_by_target[fk.target_sheet_key]:
                fields_by_target[fk.target_sheet_key].append(fk.value_field)

    id_maps = build_id_value_maps(frames, reg, fields_by_sheet=fields_by_target)

    out: dict[str, Any] = {}
    copy_reserved_frames(frames, out)
    for sheet_name, df in iter_data_frames(frames):
        fk_defs = fk_defs_by_sheet[sheet_name]
        out[sheet_name] = _apply_fk_helpers(
            df, fk_defs, id_maps, levels, helper_prefix=helper_prefix
        )

    _write_helper_provenance(out, fk_defs_by_sheet)
    return out


def _write_helper_provenance(
    out: dict[str, Any],
    fk_defs_by_sheet: dict[str, Any],
) -> None:
    """Persist derived helper provenance into ``_meta["derived"]["sheets"]``."""
    has_any_fks = any(bool(fds) for fds in fk_defs_by_sheet.values())
    existing_meta = out.get("_meta")
    has_existing_prov = bool(
        ((existing_meta or {}).get("derived") or {}).get("sheets")
    )
    if not (has_any_fks or has_existing_prov or existing_meta is not None):
        return

    meta: dict[str, Any] = dict(existing_meta or {})
    derived: dict[str, Any] = meta.setdefault("derived", {})
    derived_sheets: dict[str, Any] = derived.setdefault("sheets", {})

    for sheet_name, fk_defs in fk_defs_by_sheet.items():
        if fk_defs:
            entries = [
                {
                    "column": fk.helper_column,
                    "fk_column": fk.fk_column,
                    "target": fk.target_sheet_key,
                    "value_field": fk.value_field,
                }
                for fk in fk_defs
            ]
            # Key-selective merge: only replace helper_columns, preserve
            # other derived keys that may exist for this sheet.
            derived_sheets.setdefault(sheet_name, {})["helper_columns"] = entries
        else:
            # Remove stale provenance for sheets without current FK defs.
            if sheet_name in derived_sheets:
                derived_sheets[sheet_name].pop("helper_columns", None)
                if not derived_sheets[sheet_name]:
                    del derived_sheets[sheet_name]

    # Also clean provenance for sheets no longer in frames at all.
    current_sheets = set(fk_defs_by_sheet)
    for stale in [k for k in derived_sheets if k not in current_sheets]:
        derived_sheets[stale].pop("helper_columns", None)
        if not derived_sheets[stale]:
            del derived_sheets[stale]

    # Prune empty derived namespace.
    if not derived_sheets:
        derived.pop("sheets", None)
    if not derived:
        meta.pop("derived", None)
    out["_meta"] = meta


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def drop_helpers(frames: Frames, *, prefix: str = "_") -> Frames:
    """Remove helper columns and clean up derived provenance.

    When derived helper provenance exists in ``_meta["derived"]["sheets"]``,
    columns listed there are removed first and the provenance entries are
    cleaned up.  Prefix-based removal remains as backward-compatible fallback
    for frames without provenance metadata.
    """
    out: dict[str, Any] = {}
    copy_reserved_frames(frames, out)
    meta: dict[str, Any] = dict(out.get("_meta") or {})
    derived_sheets: dict[str, Any] = (meta.get("derived") or {}).get("sheets") or {}

    for sheet, df in iter_data_frames(frames):
        sheet_prov = (derived_sheets.get(sheet) or {}).get("helper_columns")
        if sheet_prov:
            # Metadata-backed removal: drop exactly the columns listed in provenance
            prov_cols = {entry["column"] for entry in sheet_prov}
            cols = [
                c for c in df.columns
                if _visible_label(c) not in prov_cols
            ]
            out[sheet] = df.loc[:, cols]
        else:
            # Prefix-based fallback
            cols = [c for c in df.columns if not _visible_label(c).startswith(prefix)]
            out[sheet] = df.loc[:, cols]

    _clean_helper_provenance(out, meta, derived_sheets)
    return out


def _visible_label(col: Any) -> str:
    """Extract the human-visible label from a (possibly tuple) column header."""
    if isinstance(col, tuple):
        for part in col:
            label = str(part)
            if label:
                return label
        return ""
    return str(col)


def _clean_helper_provenance(
    out: dict[str, Any],
    meta: dict[str, Any],
    derived_sheets: dict[str, Any],
) -> None:
    """Remove helper_columns provenance entries after helpers have been dropped."""
    if not derived_sheets:
        return

    for sheet_name in list(derived_sheets.keys()):
        if "helper_columns" in (derived_sheets.get(sheet_name) or {}):
            derived_sheets[sheet_name].pop("helper_columns")
            if not derived_sheets[sheet_name]:
                del derived_sheets[sheet_name]

    # Write cleaned meta back
    derived = meta.get("derived") or {}
    if derived.get("sheets") is not None and not derived["sheets"]:
        del derived["sheets"]
    if not derived:
        meta.pop("derived", None)
    out["_meta"] = meta
