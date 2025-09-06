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

    def validate(
        self,
        frames: Dict[str, pd.DataFrame],
        *,
        mode_missing_fk: str = "warn",
        mode_duplicate_ids: str = "fail",
    ) -> Dict[str, Dict[str, Any]]:
        """
        Validiert:
          - Duplicate IDs pro Zielblatt (ID-Feld aus Registry)
          - Missing FKs in Quellblättern (Spalten wie '<id_field>_(TargetKey)')

        modes: 'ignore' | 'warn' | 'fail'
        Rückgabe: report = {'duplicate_ids': {sheet:[ids...]}, 'missing_fk': {sheet:{col:[ids...]}}}
        """
        # Guards + Grundlagen
        for sheet_name, df in frames.items():
            assert_no_parentheses_in_columns(df, sheet_name)

        registry = build_registry(frames, self.defaults)
        id_maps = build_id_label_maps(frames, registry)

        log.debug("validate(): registry=%s", registry)
        for sk, mapping in id_maps.items():
            if mapping:
                sample = list(mapping.items())[:2]
                log.debug(
                    "validate(): id_map[%s]: %d keys, sample=%s",
                    sk,
                    len(mapping),
                    sample,
                )

        report: Dict[str, Dict[str, Any]] = {"duplicate_ids": {}, "missing_fk": {}}

        # --- Duplicate IDs pro Zielblatt
        for sk, meta in registry.items():
            sheet_name = meta["sheet_name"]
            id_field = meta.get("id_field", "id")
            df = frames.get(sheet_name)
            if df is None or id_field not in df.columns:
                continue

            ser = df[id_field].map(_norm_id)
            # Duplikate nur auf nicht-leeren IDs
            dup_mask = ser.notna() & ser.duplicated(keep=False)
            if bool(dup_mask.any()):
                dups: List[str] = sorted({ser.iloc[i] for i in ser[dup_mask].index})  # type: ignore[index]
                report["duplicate_ids"][sheet_name] = dups

        # --- Missing FKs pro Quellblatt
        helper_prefix = str(self.defaults.get("helper_prefix", "_"))
        for src_sheet, df in frames.items():
            # Für jedes Ziel aus Registry eine mögliche FK-Spalte prüfen:
            for sk, meta in registry.items():
                target_id = meta.get("id_field", "id")
                # Spaltenname nach unserer Konvention, z.B. "id_(A)" oder "Schluessel_(Guten_Morgen)"
                col = f"{target_id}_({sk})"
                if col not in df.columns:
                    continue

                id_map = id_maps.get(sk, {})  # bekannte Ziel-IDs als Strings
                missing: List[str] = []
                for raw in df[col].tolist():
                    norm = _norm_id(raw)
                    if norm is None:  # leere FK sind erlaubt
                        continue
                    if norm not in id_map:
                        missing.append(norm)

                if missing:
                    # structure: report['missing_fk'][src_sheet][col] = [...]
                    if src_sheet not in report["missing_fk"]:
                        report["missing_fk"][src_sheet] = {}
                    report["missing_fk"][src_sheet][col] = sorted(set(missing))

        # --- Reaktionen gemäß Modes
        # duplicates
        if report["duplicate_ids"]:
            msg = f"duplicate IDs: {report['duplicate_ids']}"
            if mode_duplicate_ids == "fail":
                raise ValueError(msg)
            elif mode_duplicate_ids == "warn":
                log.warning("validate(): %s", msg)

        # missing fk
        if report["missing_fk"]:
            msg = f"missing FKs: {report['missing_fk']}"
            if mode_missing_fk == "fail":
                raise ValueError(msg)
            elif mode_missing_fk == "warn":
                log.warning("validate(): %s", msg)

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

