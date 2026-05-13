from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ._base import WorkbookIR


@dataclass
class ColumnWidthPass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})
            widths = opts.get("column_widths") or opts.get("__column_widths")
            if widths:
                sh.meta["__column_widths"] = widths
        return doc


__all__ = ["ColumnWidthPass"]
