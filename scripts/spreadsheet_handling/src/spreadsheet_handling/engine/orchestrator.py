from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any, Dict, Iterable, Tuple

import pandas as pd

from ..core.indexing import has_level0, level0_series

log = logging.getLogger("sheets.engine")


# ---- Utils --------------------------------------------------------------------


def _sheet_key(name: str) -> str:
    """Erzeugt einen stabilen Schlüssel für Sheet-Namen (z. B. für FK-Referenzen)."""
    return name.replace(" ", "_")


def _norm_id(v: Any) -> str | None:
    """Normalisiert IDs für Vergleiche (None/NaN -> None, sonst trim zu String)."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v)
    return s.strip()


_fk_pat = re.compile(r"^(?P<idcol>[^()]+)_\((?P<target>[^()]+)\)$")


def _iter_fk_columns(df: pd.DataFrame) -> Iterable[str]:
    """
    Liefert alle Level-0-Namen, die wie FK-Spalten aussehen: 'xyz_(Target)'.
    Funktioniert auch bei einfachem Header.
    """
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = set(df.columns.get_level_values(0))
    else:
        lvl0 = set(df.columns)
    for col in lvl0:
        if isinstance(col, str) and _fk_pat.match(col):
            yield col


# ---- Reporting ----------------------------------------------------------------


@dataclass
class ValidationReport:
    duplicate_ids: Dict[str, int]              # sheet_key -> anzahl duplizierter IDs
    missing_fks: Dict[Tuple[str, str], int]    # (sheet_key, fk_column) -> anzahl fehlender
    ok: bool

    def has_duplicates(self) -> bool:
        return any(n > 0 for n in self.duplicate_ids.values())

    def has_missing_fk(self) -> bool:
        return any(n > 0 for n in self.missing_fks.values())


# ---- Engine -------------------------------------------------------------------


class Engine:
    """
    Orchestrator für Validierungen und (indirekt) FK-Helper.
    Erwartet ein 'defaults'-Dict aus der CLI / Config.
    """

    def __init__(self, defaults: Dict[str, Any] | None = None) -> None:
        self.defaults: Dict[str, Any] = defaults or {}
        # Standardfelder mit sinnvollen Defaults
        self.id_field: str = self.defaults.get("id_field", "id")
        self.label_field: str = self.defaults.get("label_field", "name")
        self.detect_fk: bool = bool(self.defaults.get("detect_fk", True))

    # -- Registry / ID-Label-Maps ------------------------------------------------

    def _build_registry(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, str]]:
        """
        Baut ein Registry-Objekt:
          sheet_key -> { sheet_name, id_field, label_field }
        (Aktuell global gleiche Felder; wenn später pro-Sheet-Overrides kommen,
         wird hier die Stelle sein.)
        """
        reg: Dict[str, Dict[str, str]] = {}
        for sheet_name in frames.keys():
            reg[_sheet_key(sheet_name)] = {
                "sheet_name": sheet_name,
                "id_field": self.id_field,
                "label_field": self.label_field,
            }
        log.debug("validate(): registry=%s", reg)
        return reg

    def _build_id_label_maps(
        self, frames: Dict[str, pd.DataFrame], reg: Dict[str, Dict[str, str]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        sheet_key -> { normalized_id -> label_or_None }
        Nur Sheets mit vorhandenem id_field werden aufgenommen; 'last-one-wins'.
        """
        maps: Dict[str, Dict[str, Any]] = {}
        for skey, meta in reg.items():
            df = frames[meta["sheet_name"]]
            if not has_level0(df, meta["id_field"]):
                # kein ID-Feld -> kein Ziel für FKs
                continue
            ids = level0_series(df, meta["id_field"]).astype("string")
            labels = (
                level0_series(df, meta["label_field"]).astype("string")
                if has_level0(df, meta["label_field"])
                else pd.Series([None] * len(ids), index=ids.index)
            )
            m: Dict[str, Any] = {}
            # last-one-wins: iteriere in Originalreihenfolge -> Überschreiben durch spätere Zeilen
            for rid, lbl in zip(ids.tolist(), labels.tolist()):
                key = _norm_id(rid)
                if key is None:
                    continue
                m[key] = lbl
            maps[skey] = m
        return maps

    # -- Validate ----------------------------------------------------------------

    def validate(
        self,
        frames: Dict[str, pd.DataFrame],
        *,
        mode_missing_fk: str = "warn",      # 'ignore' | 'warn' | 'fail'
        mode_duplicate_ids: str = "warn",   # 'ignore' | 'warn' | 'fail'
    ) -> ValidationReport:
        """
        Prüft (1) doppelte IDs in Zielsheets und (2) fehlende FK-Referenzen.
        """
        reg = self._build_registry(frames)
        id_maps = self._build_id_label_maps(frames, reg)

        # 1) Doppelte IDs je Zielsheet (nur, wenn id_field vorhanden)
        dup_by_sheet: Dict[str, int] = {}
        for skey, meta in reg.items():
            df = frames[meta["sheet_name"]]
            if not has_level0(df, self.id_field):
                dup_by_sheet[skey] = 0
                continue
            ids = level0_series(df, self.id_field).astype("string")
            # Anzahl doppelter (bezogen auf KEEP LAST)
            dups = ids.duplicated(keep="last").sum()
            dup_by_sheet[skey] = int(dups)

        # 2) Fehlende FK-Referenzen je (Quellsheet, FK-Spalte)
        miss_by_fk: Dict[Tuple[str, str], int] = {}
        for sheet_name, df in frames.items():
            skey = _sheet_key(sheet_name)
            for fkcol in _iter_fk_columns(df):
                target_key = _fk_pat.match(fkcol).group("target")  # type: ignore[union-attr]
                target_map = id_maps.get(target_key, {})
                # Falls MultiIndex, bekommen wir die Level-0-Spalte robust:
                fk_series = level0_series(df, fkcol)
                missing = 0
                for raw in fk_series.tolist():
                    key = _norm_id(raw)
                    if key is None:
                        continue
                    if key not in target_map:
                        missing += 1
                miss_by_fk[(skey, fkcol)] = missing

        # Logging + Eskalation
        if mode_duplicate_ids != "ignore":
            for skey, n in dup_by_sheet.items():
                if n:
                    msg = f"{skey}: {n} doppelte ID(s) (last-one-wins)."
                    if mode_duplicate_ids == "fail":
                        log.error(msg)
                    else:
                        log.warning(msg)
        if mode_missing_fk != "ignore":
            for (skey, fkcol), n in miss_by_fk.items():
                if n:
                    msg = f"{skey}.{fkcol}: {n} fehlende FK-Referenz(en)."
                    if mode_missing_fk == "fail":
                        log.error(msg)
                    else:
                        log.warning(msg)

        report = ValidationReport(duplicate_ids=dup_by_sheet, missing_fks=miss_by_fk, ok=True)

        # Raisen je nach Modi
        if mode_duplicate_ids == "fail" and any(n > 0 for n in dup_by_sheet.values()):
            raise ValueError("Duplicate IDs gefunden.")
        if mode_missing_fk == "fail" and any(n > 0 for n in miss_by_fk.values()):
            raise ValueError("Fehlende FK-Referenzen gefunden.")

        return report

    # -- FK-Helper (dünner Wrapper) ---------------------------------------------

    def apply_fk_helpers(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        Dünner Wrapper um core.fk.apply_fk_helpers, damit der Aufruf im Orchestrator
        zentral bleibt. Signatur der Core-Funktion kann variieren; wir versuchen
        erst (frames, defaults), dann (frames, **defaults), sonst (frames).
        """
        from ..core import fk as _fk

        func = getattr(_fk, "apply_fk_helpers")
        try:
            return func(frames, self.defaults)  # type: ignore[misc]
        except TypeError:
            try:
                return func(frames, **self.defaults)  # type: ignore[misc]
            except TypeError:
                return func(frames)  # type: ignore[misc]

