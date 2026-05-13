from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ._base import WorkbookIR


@dataclass
class FreezePass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})
            if opts.get("freeze_header", False):
                if sh.tables:
                    t = sh.tables[0]
                    sh.meta["__freeze"] = {"row": t.top + t.header_rows, "col": t.left}
                else:
                    sh.meta["__freeze"] = {"row": 2, "col": 1}
        return doc


__all__ = ["FreezePass"]
