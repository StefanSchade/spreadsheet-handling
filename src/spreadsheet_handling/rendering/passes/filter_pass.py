from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ._base import WorkbookIR


@dataclass
class FilterPass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})
            if not opts.get("auto_filter", True):
                continue
            if not sh.tables:
                continue
            t = sh.tables[0]
            if t.n_cols == 0 or t.n_rows == 0:
                continue
            sh.meta["__autofilter"] = {
                "top_left": (t.top, t.left),
                "bottom_right": (t.top + t.n_rows - 1, t.left + t.n_cols - 1),
            }
        return doc


__all__ = ["FilterPass"]
