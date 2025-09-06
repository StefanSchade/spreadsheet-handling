# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, List, Hashable, Set
import pandas as pd

from .fk import build_registry, build_id_label_maps, detect_fk_columns


def _get_target_key(fk_def: Any) -> str | None:
    # robust: akzeptiert dict oder tupel
    if isinstance(fk_def, dict):
        return fk_def.get("target_key")
    if isinstance(fk_def, tuple) and len(fk_def) >= 2:
        return fk_def[1]
    return None


def _get_col(fk_def: Any) -> str | None:
    if isinstance(fk_def, dict):
        return fk_def.get("col")
    if isinstance(fk_def, tuple) and len(fk_def) >= 1:
        return fk_def[0]
    return None


def detect_duplicate_ids(
    frames: Dict[str, pd.DataFrame],
    registry: Dict[str, Any],
) -> Dict[str, List[Hashable]]:
    """Finde doppelte IDs je Blatt anhand des id_field aus der Registry."""
    duplicates: Dict[str, List[Hashable]] = {}
    for sheet_key, meta in registry.items():
        df = frames.get(sheet_key)
        if df is None:
            continue
        id_field = meta.get("id_field", "id")
        if id_field not in df.columns:
            continue
        ser = df[id_field]
        dup_vals = sorted(pd.unique(ser[ser.duplicated(keep=False)]))
        if dup_vals:
            duplicates[sheet_key] = list(dup_vals)
    return duplicates


def detect_missing_foreign_keys(
    frames: Dict[str, pd.DataFrame],
    registry: Dict[str, Any],
    helper_prefix: str = "_",
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Finde fehlende FK-Referenzen: pro Blatt + FK-Spalte Liste mit
    {column, target, count, missing_values, rows}.
    """
    id_maps = build_id_label_maps(frames, registry)
    report: Dict[str, List[Dict[str, Any]]] = {}

    for sheet_key, df in frames.items():
        fk_defs = detect_fk_columns(df, registry, helper_prefix=helper_prefix)
        issues_for_sheet: List[Dict[str, Any]] = []

        for fk in fk_defs:
            col = _get_col(fk)
            tgt = _get_target_key(fk)
            if not col or not tgt:
                continue

            valid_ids: Set[Hashable] = set(id_maps.get(tgt, {}).keys())
            ser = df[col]
            mask = ser.notna() & (~ser.isin(list(valid_ids)))

            if mask.any():
                issues_for_sheet.append(
                    {
                        "column": col,
                        "target": tgt,
                        "count": int(mask.sum()),
                        "missing_values": pd.unique(ser[mask]).tolist(),
                        "rows": df.index[mask].tolist(),
                    }
                )

        if issues_for_sheet:
            report[sheet_key] = issues_for_sheet

    return report


def build_validation_report(
    frames: Dict[str, pd.DataFrame],
    defaults: Dict[str, Any],
) -> Dict[str, Any]:
    """Kompaktes Report-Objekt für Engine/CLI."""
    registry = build_registry(frames, defaults)
    helper_prefix = str(defaults.get("helper_prefix", "_"))

    dup = detect_duplicate_ids(frames, registry)
    miss = detect_missing_foreign_keys(frames, registry, helper_prefix=helper_prefix)

    return {"duplicate_ids": dup, "missing_fk": miss}
