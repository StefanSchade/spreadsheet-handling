"""Shared replace-or-clear policy for sheet-local presentation metadata.

Two backend parsers (XLSX `openpyxl_parser` and ODS `odf_parser`) need to
project their parsed carrier state for sheet-local presentation metadata
families (`column_widths`, `text_orientations`, `horizontal_alignments`) into
the hidden `workbook_meta_blob` payload that gets re-serialised on save.

The policy is identical across backends and across families: the carrier is
authoritative. A non-empty extraction replaces the persisted entry for that
sheet and that family; an empty extraction removes any persisted entry so the
next roundtrip cannot silently reapply formatting the user has just removed.

Before this helper, the policy was duplicated as four similarly-shaped
functions plus two inline blocks across the two backend parsers, and three of
those copies missed the clear branch entirely. See
`docs/backlog/FTR-PRESENTATION-META-CARRIER-AUTHORITY-P5.adoc`.

This module is intentionally backend-neutral: it operates only on the
``workbook_meta`` dict that both backends already build and re-serialise via
``_store_workbook_meta``. It does not import openpyxl, odfpy, pandas, or any
backend-specific package.
"""

from __future__ import annotations

from typing import Any


def apply_cell_addressed_presentation_meta(
    workbook_meta: dict[str, Any],
    sheet_name: str,
    family_key: str,
    value: dict[str, dict] | None,
) -> bool:
    """Project parsed carrier state for a sheet-local presentation family
    into the embedded workbook-meta payload, with replace-or-clear semantics.

    Carrier state is authoritative for the family:

    * ``value`` truthy and equal to the existing entry → no-op, return ``False``.
    * ``value`` truthy and different → wholesale replace
      ``workbook_meta["sheets"][sheet_name][family_key]``, return ``True``.
    * ``value`` empty / ``None`` and an entry exists →
      ``del workbook_meta["sheets"][sheet_name][family_key]``, return ``True``.
    * ``value`` empty / ``None`` and no entry exists → no-op, return ``False``.

    The helper does not create ``workbook_meta["sheets"]`` or a per-sheet
    entry on a no-op clear path, so writing an unchanged file does not
    surface previously-absent keys.

    ``family_key`` is a free-form string. Despite the function name's
    ``cell_addressed`` prefix, the helper stores whatever the extractor
    returns and does not validate the address shape — both cell-addressed
    families (``text_orientations``, ``horizontal_alignments``) and the
    dimension-addressed ``column_widths`` family share this same policy.
    """
    raw_sheets = workbook_meta.get("sheets")
    raw_sheet_meta = (
        raw_sheets.get(sheet_name)
        if isinstance(raw_sheets, dict) and isinstance(raw_sheets.get(sheet_name), dict)
        else None
    )

    if not value:
        if raw_sheet_meta is not None and family_key in raw_sheet_meta:
            del raw_sheet_meta[family_key]
            return True
        return False

    if not isinstance(raw_sheets, dict):
        raw_sheets = {}
        workbook_meta["sheets"] = raw_sheets
    raw_sheet_meta = raw_sheets.setdefault(sheet_name, {})
    if not isinstance(raw_sheet_meta, dict):
        raw_sheet_meta = {}
        raw_sheets[sheet_name] = raw_sheet_meta

    if raw_sheet_meta.get(family_key) == value:
        return False
    raw_sheet_meta[family_key] = value
    return True


__all__ = ["apply_cell_addressed_presentation_meta"]
