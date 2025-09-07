# scripts/spreadsheet_handling/src/spreadsheet_handling/engine/orchestrator.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import pandas as pd

from ..core.indexing import has_level0, level0_series
from ..core.fk import detect_fk_columns, apply_fk_helpers as _apply_fk_helpers

log = logging.getLogger("sheets.engine")


# ---------- kleine Utils --------------------------------------------------------

def _sheet_key(name: str) -> str:
    # Stabiler Schlüssel für Sheet-Namen (für FK-Referenzen etc.)
    return str(name).replace(" ", "_")


def _norm_id(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    return str(v).strip()


# ---------- (weiterhin exportiert, auch wenn intern nicht mehr benutzt) ---------

@dataclass
class ValidationReport:
    duplicate_ids: Dict[str, int]              # sheet_key -> Anzahl doppelter IDs
    missing_fks: Dict[Tuple[str, str], int]    # (sheet_key, fk_column) -> Anzahl fehlender
    ok: bool

    def has_duplicates(self) -> bool:
        return any(n > 0 for n in self.duplicate_ids.values())

    def has_missing_fk(self) -> bool:
        return any(n > 0 for n in self.missing_fks.values())


# ---------- Engine ---------------------------------------------------------------

class Engine:
    """
    Orchestrator für Validierungen und FK-Helper.
    Erwartet ein 'defaults'-Dict aus der CLI / Config.
    """

    def __init__(self, defaults: Dict[str, Any] | None = None) -> None:
        self.defaults: Dict[str, Any] = defaults or {}
        self.id_field: str = self.defaults.get("id_field", "id")
        self.label_field: str = self.defaults.get("label_field", "name")
        self.detect_fk: bool = bool(self.defaults.get("detect_fk", True))

    # -- Registry / ID-Label-Maps ------------------------------------------------

    def _build_registry(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
        """
        sheet_key -> { sheet_name, id_field, label_field }
        (Global identisch; spätere per-Sheet Overrides könnten hier einfließen.)
        """
        reg: Dict[str, Dict[str, Any]] = {}
        for sheet_name in frames.keys():
            reg[_sheet_key(sheet_name)] = {
                "sheet_name": sheet_name,
                "id_field": self.id_field,
                "label_field": self.label_field,
            }
        log.debug("validate(): registry=%s", reg)
        return reg

    def _build_id_label_maps(
        self, frames: Dict[str, pd.DataFrame], reg: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        sheet_key -> { normalized_id -> label_or_None }
        Nur Sheets mit vorhandenem id_field werden aufgenommen; 'last-one-wins'.
        """
        maps: Dict[str, Dict[str, Any]] = {}
        for skey, meta in reg.items():
            df = frames[meta["sheet_name"]]
            id_col = meta["id_field"]
            label_col = meta["label_field"]

            if not has_level0(df, id_col):
                # kein ID-Feld -> kein Ziel für FKs
                maps[skey] = {}
                continue

            ids = level0_series(df, id_col).astype("string")
            if has_level0(df, label_col):
                labels = level0_series(df, label_col).astype("string")
            else:
                labels = pd.Series([None] * len(ids), index=ids.index)

            m: Dict[str, Any] = {}
            # last-one-wins durch einfaches Überschreiben in Reihenfolge
            for rid, lbl in zip(ids.tolist(), labels.tolist()):
                key = _norm_id(rid)
                if key is None:
                    continue
                m[key] = lbl if (lbl is None or not pd.isna(lbl)) else None
            maps[skey] = m
        return maps

    # -- Validate ----------------------------------------------------------------

    def validate(
        self,
        frames: Dict[str, pd.DataFrame],
        *,
        mode_missing_fk: str = "warn",      # 'ignore' | 'warn' | 'fail'
        mode_duplicate_ids: str = "warn",   # 'ignore' | 'warn' | 'fail'
    ) -> Dict[str, Any]:
        """
        Prüft (1) doppelte IDs in Zielsheets und (2) fehlende FK-Referenzen.

        Rückgabe (von Tests erwartet):
        {
          "duplicate_ids": { "<SheetName>": ["<dup_id>", ...], ... },  # nur, wenn es Duplikate gibt
          "missing_fk": { "<SheetName>": [ {"column": "...", "missing_values": ["..."]}, ... ], ... }
        }
        """
        reg = self._build_registry(frames)
        id_maps = self._build_id_label_maps(frames, reg)

        # 1) Doppelte IDs je Zielsheet (nur, wenn id_field vorhanden)
        dups_by_sheet: Dict[str, List[str]] = {}
        for skey, meta in reg.items():
            sheet_name = meta["sheet_name"]
            id_col = meta["id_field"]
            df = frames[sheet_name]

            if not has_level0(df, id_col):
                continue

            ids = level0_series(df, id_col).astype("string")
            counts = ids.value_counts(dropna=False)
            dups = [str(idx) for idx, cnt in counts.items() if cnt > 1 and str(idx) != "nan"]
            if dups:
                dups_by_sheet[sheet_name] = dups

        if dups_by_sheet:
            msg = f"duplicate IDs: {dups_by_sheet}"
            if mode_duplicate_ids == "fail":
                log.error(msg)
                raise ValueError(msg)
            elif mode_duplicate_ids == "warn":
                log.warning(msg)

        # 2) Fehlende FK-Referenzen je Quellsheet (detailliert pro Spalte)
        missing_by_sheet: Dict[str, List[Dict[str, Any]]] = {}
        if self.detect_fk:
            helper_prefix = str(self.defaults.get("helper_prefix", "_"))
            for sheet_name, df in frames.items():
                fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
                if not fk_defs:
                    continue

                for fk in fk_defs:
                    # flexibel, ob dataclass oder dict
                    if isinstance(fk, dict):
                        col = fk.get("column")
                        target_key = fk.get("target_key") or fk.get("target_sheet_key")
                    else:
                        col = getattr(fk, "fk_column", None) or getattr(fk, "column", None)
                        target_key = getattr(fk, "target_sheet_key", None) or getattr(fk, "target_key", None)
                    if not col or not target_key:
                        continue

                    if col not in df.columns:
                        continue  # defensive

                    vals = level0_series(df, col).astype("string")
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
                # Enthält 'missing' (Tests prüfen darauf)
                raise ValueError(f"missing FK references: {missing_by_sheet}")
            elif mode_missing_fk == "warn":
                # kompakter fürs Log
                compact = {
                    s: {iss["column"]: iss["missing_values"] for iss in issues}
                    for s, issues in missing_by_sheet.items()
                }
                log.warning("missing FK references: %s", compact)

        report: Dict[str, Any] = {"duplicate_ids": dups_by_sheet, "missing_fk": missing_by_sheet}
        log.debug("validate report=%s", report)
        return report

    # -- FK-Helper ----------------------------------------------------------------

    def apply_fks(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        Findet FK-Spalten und fügt _<Ziel>_name-Helper hinzu.
        Nutzt die Core-Funktionen detect_fk_columns + apply_fk_helpers mit korrekter Signatur.
        """
        if not self.detect_fk:
            return frames

        reg = self._build_registry(frames)
        id_maps = self._build_id_label_maps(frames, reg)

        # Debug: kleine Stichprobe
        for key, m in id_maps.items():
            sample = list(m.items())[:2]
            log.debug("apply_fks(): id_map[%s]: %d keys, sample=%s", key, len(m), sample)

        levels = int(self.defaults.get("levels", 3))
        helper_prefix = str(self.defaults.get("helper_prefix", "_"))

        out: Dict[str, pd.DataFrame] = {}
        for sheet_name, df in frames.items():
            fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
            out[sheet_name] = _apply_fk_helpers(
                df, fk_defs, id_maps, levels, helper_prefix=helper_prefix
            )
        return out

    # Alias (für eventuelle Altaufrufe)
    def apply_fk_helpers(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        return self.apply_fks(frames)

