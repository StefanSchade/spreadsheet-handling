from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ._base import SheetIR, WorkbookIR


@dataclass
class MetaPass:
    minimal_fields: Optional[List[str]] = None

    def __post_init__(self):
        if self.minimal_fields is None:
            self.minimal_fields = ["version", "exported_at", "author"]

    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        meta: SheetIR = doc.hidden_sheets.get("_meta") or SheetIR(name="_meta", meta={})
        if "_meta" not in doc.hidden_sheets:
            doc.hidden_sheets["_meta"] = meta
        for f in self.minimal_fields or []:
            meta.meta.setdefault(f, "")
        meta.meta["_hidden"] = True
        return doc


__all__ = ["MetaPass"]
