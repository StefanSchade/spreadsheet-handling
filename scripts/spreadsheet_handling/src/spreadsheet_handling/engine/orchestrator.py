from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from spreadsheet_handling.core.fk import (
    apply_fk_helpers,
    assert_no_parentheses_in_columns,
    build_id_label_maps,
    build_registry,
    detect_fk_columns,
)
from spreadsheet_handling.logging_utils import get_logger

log = get_logger("engine")


class Engine:
    """Orchestriert FK-Logik, Validierung, Logging – hält CLI-spezifisches raus."""

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
        mode_duplicate_ids: str = "warn",
    ) -> None:
        """
        Leichtgewichtige Validierung (derzeit: Guards + Indexaufbau + Logging).
        Hook ist bewusst da – 'fail'/'warn' werden später in Phase 5 schärfer
        umgesetzt (du wolltest die Schalter schon mal im CLI haben).

        Aktuell:
        - Klammern-Guard (wie zuvor)
        - Registry + ID-Maps werden aufgebaut (und geloggt)
        - Keine Exceptions (auch bei 'fail' noch no-op) – kompatibel mit bestehenden Tests
        """
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

        # Phase 5 (später): hier je nach mode_* echte Prüfungen (duplicates/missing FKs) mit
        # raise/warn/ignore implementieren. Für die aktuelle Test-Suite bleibt dies no-op.

    def apply_fks(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        FK-Helper-Spalten hinzufügen (z. B. _Target_name) – nur wenn detect_fk=True.
        """
        # Gleicher Guard wie zuvor:
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
            fk_defs = detect_fk_columns(df, registry, helper_prefix=helper_prefix)
            if not fk_defs:
                out[sheet_name] = df
                continue
            out[sheet_name] = apply_fk_helpers(
                df,
                fk_defs,
                id_maps,
                levels=levels,
                helper_prefix=helper_prefix,
            )
        return out
