"""Helper-column removal and cleanup entry point.

Behavior-preserving split out of the former single ``fk_helpers`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-FK-HELPERS-P5).
"""
from __future__ import annotations

from typing import Any

from ....frame_keys import copy_reserved_frames, iter_data_frames

from .provenance import _clean_helper_provenance, _visible_label

Frames = dict[str, Any]


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
