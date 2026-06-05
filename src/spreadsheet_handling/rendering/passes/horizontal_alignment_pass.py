from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ._base import WorkbookIR


@dataclass
class HorizontalAlignmentPass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})
            alignments = opts.get("horizontal_alignments") or opts.get(
                "__horizontal_alignments"
            )
            if alignments:
                sh.meta["__horizontal_alignments"] = alignments
        return doc


__all__ = ["HorizontalAlignmentPass"]
