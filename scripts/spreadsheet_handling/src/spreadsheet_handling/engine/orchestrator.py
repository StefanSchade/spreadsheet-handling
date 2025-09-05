from __future__ import annotations
from typing import Dict, Any
import pandas as pd

from spreadsheet_handling.core.fk import (
    build_registry,
    build_id_label_maps,
    detect_fk_columns,
    apply_fk_helpers,
    assert_no_parentheses_in_columns,
)
from spreadsheet_handling.logging_utils import get_logger

log = get_logger("engine")


class Engine:
    def __init__(self, defaults: Dict[str, Any]):
        self.defaults = defaults

    def apply_fks(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        # gleiches Guard wie vorher:
        for sheet_name, df in frames.items():
            assert_no_parentheses_in_columns(df, sheet_name)

        registry = build_registry(frames, self.defaults)
        id_maps = build_id_label_maps(frames, registry)

        log.debug("registry=%s", registry)
        for sk, m in id_maps.items():
            if m:
                sample = list(m.items())[:2]
                log.debug("id_map[%s]: %d keys, sample=%s", sk, len(m), sample)

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
                df, fk_defs, id_maps, levels=levels, helper_prefix=helper_prefix
            )
        return out

