from __future__ import annotations
from typing import Dict, Any
import pandas as pd
from spreadsheet_handling.core.fk import (
    build_registry, build_id_label_maps, detect_fk_columns, apply_fk_helpers,
    assert_no_parentheses_in_columns
)

class Engine:
    def __init__(self, defaults: Dict[str, Any]):
        self.defaults = defaults

    def apply_fks(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        # validation & FK helpers
        for sheet, df in frames.items():
            assert_no_parentheses_in_columns(df, sheet)
        registry = build_registry(frames, self.defaults)
        id_maps = build_id_label_maps(frames, registry)
        if not bool(self.defaults.get("detect_fk", True)):
            return frames
        helper_prefix = str(self.defaults.get("helper_prefix", "_"))
        levels = int(self.defaults.get("levels", 3))
        out = {}
        for sheet, df in frames.items():
            fk_defs = detect_fk_columns(df, registry, helper_prefix=helper_prefix)
            out[sheet] = apply_fk_helpers(df, fk_defs, id_maps, levels=levels, helper_prefix=helper_prefix)
        return out

