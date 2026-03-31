# scripts/spreadsheet_handling/src/spreadsheet_handling/engine/orchestrator.py
"""
Thin backward-compatibility shim.

All business logic now lives in core/fk.py (pure functions).
Pipeline factories in pipeline/pipeline.py call core/fk directly.
Engine is kept only for legacy_pre_hex tests and any external callers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import pandas as pd

from ..core.indexing import has_level0, level0_series
from ..core.fk import (
    build_registry,
    build_id_label_maps,
    detect_fk_columns,
    apply_fk_helpers as _apply_fk_helpers,
)

log = logging.getLogger("sheets.engine")


# ---------- Utils (kept for backward compat) ------------------------------------

def _sheet_key(name: str) -> str:
    return str(name).replace(" ", "_")


def _norm_id(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    return str(v).strip()


# ---------- Typed report --------------------------------------------------------

@dataclass
class ValidationReport:
    duplicate_ids: Dict[str, int]
    missing_fks: Dict[Tuple[str, str], int]
    ok: bool

    def has_duplicates(self) -> bool:
        return any(n > 0 for n in self.duplicate_ids.values())

    def has_missing_fk(self) -> bool:
        return any(n > 0 for n in self.missing_fks.values())


# ---------- Engine (backward-compat shim) ----------------------------------------


class Engine:
    """
    Backward-compatibility shim. Delegates to core/fk pure functions.
    New code should use pipeline steps or core/fk functions directly.
    """

    def __init__(self, defaults: Dict[str, Any] | None = None) -> None:
        self.defaults: Dict[str, Any] = defaults or {}
        self.id_field: str = self.defaults.get("id_field", "id")
        self.label_field: str = self.defaults.get("label_field", "name")
        self.detect_fk: bool = bool(self.defaults.get("detect_fk", True))

    def _build_registry(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
        return build_registry(frames, self.defaults)

    def _build_id_label_maps(
        self, frames: Dict[str, pd.DataFrame], reg: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        return build_id_label_maps(frames, reg)

    def validate(
        self,
        frames: Dict[str, pd.DataFrame],
        *,
        mode_missing_fk: str = "warn",
        mode_duplicate_ids: str = "warn",
    ) -> Dict[str, Any]:
        reg = self._build_registry(frames)
        id_maps = self._build_id_label_maps(frames, reg)

        # 1) Duplicate IDs
        dups_by_sheet: Dict[str, List[str]] = {}
        for skey, meta in reg.items():
            sheet_name = meta["sheet_name"]
            df = frames[sheet_name]
            if not has_level0(df, self.id_field):
                continue
            ids = level0_series(df, self.id_field).astype("string")
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

        # 2) Missing FK references
        missing_by_sheet: Dict[str, List[Dict[str, Any]]] = {}
        if self.detect_fk:
            helper_prefix = str(self.defaults.get("helper_prefix", "_"))
            for sheet_name, df in frames.items():
                fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
                for fk in fk_defs:
                    col = fk.fk_column
                    target_key = fk.target_sheet_key
                    if col not in df.columns:
                        continue
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
                raise ValueError(f"missing FK references: {missing_by_sheet}")
            elif mode_missing_fk == "warn":
                compact = {
                    s: {iss["column"]: iss["missing_values"] for iss in issues}
                    for s, issues in missing_by_sheet.items()
                }
                log.warning("missing FK references: %s", compact)

        return {"duplicate_ids": dups_by_sheet, "missing_fk": missing_by_sheet}

    def apply_fks(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        if not self.detect_fk:
            return frames

        reg = self._build_registry(frames)
        id_maps = self._build_id_label_maps(frames, reg)

        levels = int(self.defaults.get("levels", 3))
        helper_prefix = str(self.defaults.get("helper_prefix", "_"))

        out: Dict[str, pd.DataFrame] = {}
        for sheet_name, df in frames.items():
            fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
            out[sheet_name] = _apply_fk_helpers(
                df, fk_defs, id_maps, levels, helper_prefix=helper_prefix
            )
        return out

    def apply_fk_helpers(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        return self.apply_fks(frames)
