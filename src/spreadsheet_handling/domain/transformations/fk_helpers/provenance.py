"""Writing and cleaning ``_meta.derived`` FK helper-column provenance.

Behavior-preserving split out of the former single ``fk_helpers`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-FK-HELPERS-P5). ``_visible_label`` is
kept local here because both provenance cleanup and ``drop.drop_helpers``
need it; ``drop`` imports it from this module.

FK cleanup owns only its own ``helper_columns`` subkey. A sibling
``enrich_lookup`` provenance record may also live under the same
``_meta.derived.sheets.<sheet>`` entry; whether that record is still
truthful after FK's column removal is Lookup's own semantic call, not FK's
(H5 in the FK/Lookup Cycle-0 assessment). ``_clean_helper_provenance`` asks
the Lookup-owned boundary rather than interpreting the record's shape here.
"""
from __future__ import annotations

from typing import Any

from ..enrich_lookup import reconcile_enrich_lookup_provenance


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
    derived: dict[str, Any] = meta.get("derived", {})
    derived_sheets: dict[str, Any] = derived.get("sheets", {})
    path_copied = False

    def copy_derived_path() -> None:
        """Detach the FK-owned provenance path before its first mutation."""
        nonlocal derived, derived_sheets, path_copied
        if path_copied:
            return
        derived = dict(derived)
        derived_sheets = dict(derived_sheets)
        derived["sheets"] = derived_sheets
        meta["derived"] = derived
        path_copied = True

    for sheet_name, fk_defs in fk_defs_by_sheet.items():
        if fk_defs:
            entries = [
                {
                    "column": fk.helper_column,
                    "fk_column": fk.fk_column,
                    "target": fk.target_sheet_key,
                    "target_key": fk.id_field,
                    "value_field": fk.value_field,
                }
                for fk in fk_defs
            ]
            # Key-selective merge: only replace helper_columns, preserve
            # other derived keys that may exist for this sheet.
            copy_derived_path()
            sheet_entry = dict(derived_sheets.get(sheet_name, {}))
            sheet_entry["helper_columns"] = entries
            derived_sheets[sheet_name] = sheet_entry
        else:
            # Remove stale provenance for sheets without current FK defs.
            if sheet_name in derived_sheets:
                sheet_entry = derived_sheets[sheet_name]
                if "helper_columns" not in sheet_entry and sheet_entry:
                    continue
                copy_derived_path()
                sheet_entry = dict(derived_sheets[sheet_name])
                sheet_entry.pop("helper_columns", None)
                if sheet_entry:
                    derived_sheets[sheet_name] = sheet_entry
                else:
                    del derived_sheets[sheet_name]

    # Also clean provenance for sheets no longer in frames at all.
    current_sheets = set(fk_defs_by_sheet)
    for stale in [k for k in derived_sheets if k not in current_sheets]:
        sheet_entry = derived_sheets[stale]
        if "helper_columns" not in sheet_entry and sheet_entry:
            continue
        copy_derived_path()
        sheet_entry = dict(derived_sheets[stale])
        sheet_entry.pop("helper_columns", None)
        if sheet_entry:
            derived_sheets[stale] = sheet_entry
        else:
            del derived_sheets[stale]

    # Prune empty derived namespace.
    if not derived_sheets:
        if "sheets" in derived and not path_copied:
            copy_derived_path()
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
    """Remove FK-owned ``helper_columns`` provenance after helpers are dropped.

    A sibling ``enrich_lookup`` record on the same sheet entry is handed to
    the Lookup-owned reconciliation boundary rather than interpreted here;
    see the module docstring for why.
    """
    if not derived_sheets:
        return

    derived: dict[str, Any] = meta.get("derived") or {}
    path_copied = False

    def copy_derived_path() -> None:
        """Detach the FK-cleanup path before its first mutation."""
        nonlocal derived, derived_sheets, path_copied
        if path_copied:
            return
        derived = dict(derived)
        derived_sheets = dict(derived_sheets)
        derived["sheets"] = derived_sheets
        meta["derived"] = derived
        path_copied = True

    for sheet_name in list(derived_sheets.keys()):
        sheet_entry = derived_sheets.get(sheet_name) or {}
        remove_helper_columns = "helper_columns" in sheet_entry

        remove_enrich_lookup = False
        if "enrich_lookup" in sheet_entry:
            frame = out.get(sheet_name)
            frame_columns = getattr(frame, "columns", None)
            present = (
                {_visible_label(c) for c in frame_columns}
                if frame_columns is not None
                else set()
            )
            retained = reconcile_enrich_lookup_provenance(
                sheet_entry["enrich_lookup"],
                frame_name=sheet_name,
                present_columns=present,
            )
            remove_enrich_lookup = not retained

        if not (remove_helper_columns or remove_enrich_lookup or not sheet_entry):
            continue

        copy_derived_path()
        sheet_entry = dict(derived_sheets.get(sheet_name) or {})
        if remove_helper_columns:
            sheet_entry.pop("helper_columns")
        if remove_enrich_lookup:
            sheet_entry.pop("enrich_lookup")
        if not sheet_entry:
            del derived_sheets[sheet_name]
        else:
            derived_sheets[sheet_name] = sheet_entry

    # Write cleaned meta back
    if derived.get("sheets") is not None and not derived["sheets"]:
        del derived["sheets"]
    if not derived:
        meta.pop("derived", None)
    out["_meta"] = meta
