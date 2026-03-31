from . import meta_pass, validation_pass, style_pass
from .core import StylePass, FilterPass, FreezePass, ValidationPass, MetaPass, NamedRangePass, IRPass
from ..ir import WorkbookIR

def apply_all(ir: WorkbookIR, meta: dict) -> WorkbookIR:
    """Apply all IR passes in deterministic order.

    Uses the CorePass classes (same as default_p1_passes in flow.py)
    so both the production path (xlsx_backend) and the test/DTO path
    (flow.py) execute the same logic.

    The workbook-level *meta* dict is stashed on the hidden _meta sheet
    by the composer, so ValidationPass can read constraints from there.
    """
    # Ensure meta is stashed if not already (for callers that pass meta separately)
    if meta:
        from ..ir import SheetIR
        meta_sheet = ir.hidden_sheets.setdefault("_meta", SheetIR(name="_meta"))
        if "workbook_meta_blob" not in meta_sheet.meta:
            meta_sheet.meta["workbook_meta_blob"] = meta

    passes: list[IRPass] = [MetaPass(), ValidationPass(), StylePass(), FilterPass(), FreezePass(), NamedRangePass()]
    for p in passes:
        ir = p.apply(ir)
    return ir
