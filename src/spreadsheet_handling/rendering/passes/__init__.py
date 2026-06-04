from __future__ import annotations

import json

from ._base import IRPass
from .column_width_pass import ColumnWidthPass
from .filter_pass import FilterPass
from .freeze_pass import FreezePass
from .meta_pass import MetaPass
from .named_range_pass import NamedRangePass
from .protection_pass import ProtectionPass
from .style_pass import StylePass
from .text_orientation_pass import TextOrientationPass
from .validation_pass import ValidationPass
from ..ir import WorkbookIR


def default_passes() -> list[IRPass]:
    return [
        MetaPass(),
        ValidationPass(),
        StylePass(),
        ProtectionPass(),
        FilterPass(),
        FreezePass(),
        ColumnWidthPass(),
        TextOrientationPass(),
        NamedRangePass(),
    ]


def apply_all(ir: WorkbookIR, meta: dict) -> WorkbookIR:
    """Apply all IR passes in deterministic order."""
    if meta:
        from ..ir import SheetIR

        meta_sheet = ir.hidden_sheets.setdefault("_meta", SheetIR(name="_meta"))
        if "workbook_meta_blob" not in meta_sheet.meta:
            meta_sheet.meta["workbook_meta_blob"] = json.dumps(
                meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )

    for pass_ in default_passes():
        ir = pass_.apply(ir)
    return ir


__all__ = [
    "ColumnWidthPass",
    "FilterPass",
    "FreezePass",
    "IRPass",
    "MetaPass",
    "NamedRangePass",
    "ProtectionPass",
    "StylePass",
    "TextOrientationPass",
    "ValidationPass",
    "apply_all",
    "default_passes",
]
