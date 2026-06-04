from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ._base import WorkbookIR


@dataclass
class TextOrientationPass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})
            orientations = opts.get("text_orientations") or opts.get("__text_orientations")
            if orientations:
                sh.meta["__text_orientations"] = orientations
        return doc


__all__ = ["TextOrientationPass"]
