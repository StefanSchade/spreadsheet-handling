"""Writing and cleaning ``_meta.derived`` FK helper-column provenance.

Behavior-preserving split out of the former single ``fk_helpers`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-FK-HELPERS-P5). ``_visible_label`` is
kept local here because both provenance cleanup and ``drop.drop_helpers``
need it; ``drop`` imports it from this module.
"""
from __future__ import annotations

from typing import Any


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
        sheet_entry = derived_sheets.get(sheet_name) or {}
        if "helper_columns" in sheet_entry:
            sheet_entry.pop("helper_columns")
        # Narrow enrich_lookup cleanup: drop the subkey only when none of its
        # helper columns remain in the cleaned frame, so still-present lookup
        # helper columns are never left without provenance.
        enrich = sheet_entry.get("enrich_lookup")
        if isinstance(enrich, dict):
            enrich_cols = {str(c) for c in (enrich.get("helper_columns") or [])}
            frame = out.get(sheet_name)
            frame_columns = getattr(frame, "columns", None)
            present = (
                {_visible_label(c) for c in frame_columns}
                if frame_columns is not None
                else set()
            )
            if not (enrich_cols & present):
                sheet_entry.pop("enrich_lookup")
        if not sheet_entry:
            del derived_sheets[sheet_name]

    # Write cleaned meta back
    derived = meta.get("derived") or {}
    if derived.get("sheets") is not None and not derived["sheets"]:
        del derived["sheets"]
    if not derived:
        meta.pop("derived", None)
    out["_meta"] = meta
