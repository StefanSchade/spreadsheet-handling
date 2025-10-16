from typing import Dict
import pandas as pd
from ..ir import WorkbookIR, SheetIR, TableBlock

def compose_workbook(frames: Dict[str, pd.DataFrame], meta: dict) -> WorkbookIR:
    wb = WorkbookIR()
    # naive: one sheet per frame, table starts at A1
    for name, df in frames.items():
        if not isinstance(df, pd.DataFrame):
            continue
        sh = SheetIR(name=name)
        sh.tables.append(TableBlock(frame_name=name, top_left=(1, 1), header_rows=1, header_cols=1))
        wb.sheets[name] = sh
    # stash the domain meta so meta_pass can persist it
    if meta:
        wb.hidden_sheets.setdefault("_meta", SheetIR(name="_meta")).meta["workbook_meta_blob"] = meta
    return wb
