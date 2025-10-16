from typing import Dict
from ..ir import WorkbookIR, SheetIR, TableBlock

def apply(ir: WorkbookIR, meta: dict) -> WorkbookIR:
    # meta already stashed by composer; later we’ll persist as hidden sheet content
    return ir
