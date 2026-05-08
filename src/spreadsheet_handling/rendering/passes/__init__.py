from . import meta_pass as meta_pass
from . import style_pass as style_pass
from . import validation_pass as validation_pass
from .core import (
    StylePass,
    FilterPass,
    FreezePass,
    ColumnWidthPass,
    ValidationPass,
    MetaPass,
    NamedRangePass,
    ProtectionPass,
    IRPass,
)
from ..ir import WorkbookIR

def apply_all(ir: WorkbookIR, meta: dict) -> WorkbookIR:
    """Apply all IR passes in deterministic order.

    Uses the CorePass classes (same as default_p1_passes in flow.py)
    so both the production spreadsheet path and the test/DTO path
    (flow.py) execute the same logic.

    The workbook-level *meta* dict is stashed on the hidden _meta sheet
    by the composer, so ValidationPass can read constraints from there.
    """
    # Ensure meta is stashed if not already (for callers that pass meta separately)
    if meta:
        from ..ir import SheetIR
        meta_sheet = ir.hidden_sheets.setdefault('_meta', SheetIR(name='_meta'))
        if 'workbook_meta_blob' not in meta_sheet.meta:
            meta_sheet.meta['workbook_meta_blob'] = meta

    passes: list[IRPass] = [
        MetaPass(),
        ValidationPass(),
        StylePass(),
        ProtectionPass(),
        FilterPass(),
        FreezePass(),
        ColumnWidthPass(),
        NamedRangePass(),
    ]
    for p in passes:
        ir = p.apply(ir)
    return ir
