# scripts/spreadsheet_handling/src/spreadsheet_handling/engine/orchestrator.py
from __future__ import annotations

from typing import Any, Dict, List
import pandas as pd

from spreadsheet_handling.core.fk import (
    detect_fk_columns,
    apply_fk_helpers,
    _series_from_first_level,
    _norm_id,
)
from spreadsheet_handling.logging_utils import get_logger

log = get_logger("engine")


def _has_level0(df: pd.DataFrame, col: str) -> bool:
    if isinstance(df.columns, pd.MultiIndex):
        return col in df.columns.get_level_values(0)
    return col in df.columns


def _sheet_key(name: str) -> str:
    """Normierter Schlüsselname (wie in den Tests zu sehen: Leerzeichen -> Unterstrich)."""
    return str(name).replace(" ", "_")


class Engine:
    """
    Hält Defaults (id_field, label_field, levels, helper_prefix, detect_fk) und
    orchestriert Validierung + Hinzufügen der FK-Helper-Spalten.
    """

    def __init__(self, defaults: Dict[str, Any] | None = None) -> None:
        d = defaults or {}
        self.defaults: Dict[str, Any] = {
            "id_field": d.get("id_field", "id"),
            "label_field": d.get("label_field", "name"),
            "levels": int(d.get("levels", 3)),
            "helper_prefix": d.get("helper_prefix", "_"),
            "detect_fk": bool(d.get("detect_fk", True)),
        }

    # ---------- intern: Registry & ID->Label-Maps ----------

    def _registry(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
        """
        Liefert pro Blatt einen Eintrag:
        key = normierter Blattname; value = {sheet_name, id_field, label_field}
        """
        reg: Dict[str, Dict[str, Any]] = {}
        for sheet_name in frames.keys():
            reg[_sheet_key(sheet_name)] = {
                "sheet_name": sheet_name,
                "id_field": self.defaults["id_field"],
                "label_field": self.defaults["label_field"],
            }
        return reg

    def _build_id_label_maps(
        self, frames: Dict[str, pd.DataFrame], reg: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Baut für jedes Zielblatt eine Map: normierte ID -> Label (oder None, wenn Label-Feld fehlt).
        Bei doppelten IDs gilt: **last one wins**.
        """
        maps: Dict[str, Dict[str, Any]] = {}

        for key, meta in reg.items():
            sheet_name = meta["sheet_name"]
            df = frames[sheet_name]
            id_col = meta["id_field"]
            label_col = meta["label_field"]

            # Quellblätter ohne ID-Feld überspringen
            if not _has_level0(df, id_col):
                maps[key] = {}  # kein Ziel, also leere Map – harmlos für Lookups
                continue

            ids = _series_from_first_level(df, id_col).astype("string")

            if _has_level0(df, label_col):
                labels = _series_from_first_level(df, label_col).astype("string")
                m: Dict[str, Any] = {}
                for rid, lbl in zip(ids.tolist(), labels.tolist()):  # last-one-wins
                    m[_norm_id(rid)] = None if pd.isna(lbl) else str(lbl)
            else:
                # kein Label-Feld: ID -> None
                m = {}
                for rid in ids.tolist():
                    m[_norm_id(rid)] = None

            maps[key] = m

        return maps

    # ---------- API: Validate & Apply ----------

    def validate(
        self,
        frames: Dict[str, pd.DataFrame],
        *,
        mode_missing_fk: str = "warn",
        mode_duplicate_ids: str = "warn",
    ) -> Dict[str, Any]:
        """
        Prüft:
          - doppelte IDs je Blatt
          - fehlende FK-Referenzen in Quellblättern

        Rückgabe (von den neuen Tests erwartet):
        {
          "duplicate_ids": { "<SheetName>": ["<dup_id>", ...], ... },
          "missing_fk": { "<SheetName>": [ {"column": "<fk_col>", "missing_values": ["..."]}, ... ], ... }
        }

        Je nach Modus wird gewarnt oder ValueError geraised.
        """
        reg = self._registry(frames)
        log.debug("validate(): registry=%s", reg)

        id_maps = self._build_id_label_maps(frames, reg)

        # ---- Doppelte IDs je Blatt sammeln
        dups_by_sheet: Dict[str, List[str]] = {}
        for key, meta in reg.items():
            sheet_name = meta["sheet_name"]
            id_col = meta["id_field"]

            # >>> NEU: nur prüfen, wenn das ID-Feld existiert
            if not _has_level0(frames[sheet_name], id_col):
                continue

            ids = _series_from_first_level(frames[sheet_name], meta["id_field"]).astype("string")
            counts = ids.value_counts(dropna=False)
            dups = [str(idx) for idx, cnt in counts.items() if cnt > 1 and str(idx) != "nan"]
            if dups:
                dups_by_sheet[sheet_name] = dups

        if dups_by_sheet:
            if mode_duplicate_ids == "fail":
                raise ValueError(f"duplicate IDs: {dups_by_sheet}")
            elif mode_duplicate_ids == "warn":
                log.warning("duplicate IDs: %s", dups_by_sheet)

        # ---- Fehlende FKs
        missing_by_sheet: Dict[str, List[Dict[str, Any]]] = {}
        if self.defaults["detect_fk"]:
            helper_prefix = str(self.defaults["helper_prefix"])
            for sheet_name, df in frames.items():
                fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
                if not fk_defs:
                    continue

                for fk in fk_defs:
                    # FKDef oder dict unterstützen
                    if isinstance(fk, dict):
                        col = fk["column"]
                        target_key = fk.get("target_key") or fk.get("target_sheet_key")
                    else:
                        col = fk.fk_column
                        target_key = fk.target_sheet_key

                    if col not in df.columns:
                        continue  # defensive

                    vals = _series_from_first_level(df, col).astype("string")
                    target_map = id_maps.get(target_key, {})
                    missing_vals = sorted(
                        {str(v) for v in vals.dropna().unique() if _norm_id(v) not in target_map}
                    )
                    if missing_vals:
                        missing_by_sheet.setdefault(sheet_name, []).append(
                            {"column": col, "missing_values": missing_vals}
                        )

        if missing_by_sheet:
            if mode_missing_fk == "fail":
                raise ValueError(f"missing FKs: {missing_by_sheet}")
            elif mode_missing_fk == "warn":
                compact = {
                    s: {iss["column"]: iss["missing_values"] for iss in issues}
                    for s, issues in missing_by_sheet.items()
                }
                log.warning("missing FKs: %s", compact)

        report = {"duplicate_ids": dups_by_sheet, "missing_fk": missing_by_sheet}
        log.debug("validate report=%s", report)
        return report

    def apply_fks(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        Findet FK-Spalten und fügt _<Ziel>_name-Helper hinzu.
        """
        if not self.defaults["detect_fk"]:
            return frames

        reg = self._registry(frames)
        log.debug("apply_fks(): registry=%s", reg)

        id_maps = self._build_id_label_maps(frames, reg)
        for key, m in id_maps.items():
            sample = list(m.items())[:2]
            log.debug("apply_fks(): id_map[%s]: %d keys, sample=%s", key, len(m), sample)

        levels = int(self.defaults["levels"])
        helper_prefix = str(self.defaults["helper_prefix"])

        out: Dict[str, pd.DataFrame] = {}
        for sheet_name, df in frames.items():
            fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
            out[sheet_name] = apply_fk_helpers(
                df, fk_defs, id_maps, levels, helper_prefix=helper_prefix
            )
        return out
