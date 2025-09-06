# scripts/spreadsheet_handling/src/spreadsheet_handling/engine/orchestrator.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

import math
import pandas as pd

from spreadsheet_handling.core.fk import (
    apply_fk_helpers,
    assert_no_parentheses_in_columns,
    build_id_label_maps,
    build_registry,
)
from spreadsheet_handling.logging_utils import get_logger

log = get_logger("engine")


def _norm_id(val: Any) -> Optional[str]:
    """Wie in der FK-Logik: IDs als string normalisieren; None für leere Werte."""
    if val is None:
        return None
    try:
        # pandas NaN / NA
        if pd.isna(val):  # type: ignore[arg-type]
            return None
    except Exception:
        pass

    # floats: 1.0 -> "1", 1.5 -> "1.5"
    if isinstance(val, float):
        if math.isfinite(val) and float(val).is_integer():
            return str(int(val))
        return str(val)
    return str(val)


class Engine:
    """Orchestriert Validierung und FK-Anreicherung (adapterfrei)."""

    def __init__(self, defaults: Dict[str, Any]):
        self.defaults = defaults or {}

    # ---------------------
    # Public API
    # ---------------------

# in scripts/spreadsheet_handling/src/spreadsheet_handling/engine/orchestrator.py

from typing import Dict, Any, List, Tuple
...
def validate(
    self,
    frames: Dict[str, pd.DataFrame],
    *,
    mode_missing_fk: str = "warn",       # "ignore" | "warn" | "fail"
    mode_duplicate_ids: str = "warn",
) -> Dict[str, Any]:
    registry = build_registry(frames, self.defaults)
    id_maps = build_id_label_maps(frames, registry)

    log.debug("validate(): registry=%s", registry)
    for sk, m in id_maps.items():
        if m:
            sample = list(m.items())[:2]
            log.debug("validate(): id_map[%s]: %d keys, sample=%s", sk, len(m), sample)

    report: Dict[str, Any] = {"duplicate_ids": {}, "missing_fk": {}}

    # --- Duplicate IDs ---
    dup_by_sheet: Dict[str, List[str]] = {}
    for sheet_name, df in frames.items():
        key = _sheet_key(sheet_name)  # so wie in deinen Helpers/Gebrauch
        id_field = registry[key]["id_field"]
        if id_field in df.columns:
            # dupe detection mit str()-Normalisierung
            vals = df[id_field].astype("string")
            dups = vals[vals.duplicated(keep="last")].unique().tolist()
            if dups:
                dup_by_sheet[sheet_name] = [str(x) for x in dups]

    if dup_by_sheet:
        if mode_duplicate_ids == "fail":
            raise ValueError(f"duplicate IDs: {dup_by_sheet}")
        elif mode_duplicate_ids == "warn":
            log.warning("duplicate IDs: %s", dup_by_sheet)
        report["duplicate_ids"] = dup_by_sheet

    # --- Missing FKs ---
    missing_by_sheet: Dict[str, List[Dict[str, Any]]] = {}
    for sheet_name, df in frames.items():
        key = _sheet_key(sheet_name)
        fk_defs = detect_fk_columns(df, registry, helper_prefix=str(self.defaults.get("helper_prefix", "_")))

        # Wir wollen mit dicts & FKDef arbeiten können
        for fk in fk_defs:
            if isinstance(fk, dict):
                col_name = fk["column"]
                target_key = fk["target_key"]
            else:
                col_name = fk.column
                target_key = fk.target_key

            target_map = id_maps.get(target_key, {})
            if col_name in df.columns:
                vals = df[col_name].astype("string")
                # Nicht-null Werte, die NICHT im Ziel vorkommen
                missing_vals = sorted({str(v) for v in vals.dropna().unique() if str(v) not in target_map})
                if missing_vals:
                    missing_by_sheet.setdefault(sheet_name, []).append(
                        {"column": col_name, "missing_values": missing_vals}
                    )

    if missing_by_sheet:
        if mode_missing_fk == "fail":
            raise ValueError(f"missing FKs: {missing_by_sheet}")
        elif mode_missing_fk == "warn":
            # fürs Log lieber kompaktes Format
            compact = {s: {iss["column"]: iss["missing_values"] for iss in issues}
                       for s, issues in missing_by_sheet.items()}
            log.warning("missing FKs: %s", compact)
        report["missing_fk"] = missing_by_sheet

    return report


    def apply_fks(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        FK-Helper-Spalten hinzufügen (z. B. _Target_name) – nur wenn detect_fk=True.
        """
        for sheet_name, df in frames.items():
            assert_no_parentheses_in_columns(df, sheet_name)

        registry = build_registry(frames, self.defaults)
        id_maps = build_id_label_maps(frames, registry)

        log.debug("apply_fks(): registry=%s", registry)
        for sk, mapping in id_maps.items():
            if mapping:
                sample = list(mapping.items())[:2]
                log.debug(
                    "apply_fks(): id_map[%s]: %d keys, sample=%s",
                    sk,
                    len(mapping),
                    sample,
                )

        if not bool(self.defaults.get("detect_fk", True)):
            return frames

        helper_prefix = str(self.defaults.get("helper_prefix", "_"))
        levels = int(self.defaults.get("levels", 3))

        out: Dict[str, pd.DataFrame] = {}
        for sheet_name, df in frames.items():
            # kleine Inline-Erkennung: welche FK-Spalten gibt's?
            # (Wir bauen den Namen wie in validate zusammen.)
            fk_cols = []
            for sk, meta in registry.items():
                target_id = meta.get("id_field", "id")
                col = f"{target_id}_({sk})"
                if col in df.columns:
                    fk_cols.append({"column": col, "target_key": sk})

            if not fk_cols:
                out[sheet_name] = df
                continue

            # apply_fk_helpers erwartet fk_defs in der Form [{'column':..., 'target_key':...}, ...]
            out[sheet_name] = apply_fk_helpers(
                df,
                fk_cols,
                id_maps,
                levels=levels,
                helper_prefix=helper_prefix,
            )
        return out

