from __future__ import annotations
from typing import Dict, Mapping, Any
import pandas as pd

from ..ir import WorkbookIR, SheetIR, TableBlock

_RESERVED_FRAME_KEYS = {"_meta"}  # extend as needed

def _flatten_header_to_strings(df: pd.DataFrame) -> list[str]:
    """
    Return a list of header strings. Supports simple Index or MultiIndex.
    MultiIndex levels are joined with ' / ' (adjust if you prefer another joiner).
    """
    if isinstance(df.columns, pd.MultiIndex):
        return [" / ".join(map(str, tup)) for tup in df.columns.tolist()]
    return [str(c) for c in df.columns.tolist()]

def compose_workbook(frames: Mapping[str, Any], meta: Dict[str, Any] | None) -> WorkbookIR:
    """
    Build a naive 1-table-per-sheet IR:
      - Table starts at A1 (top=1, left=1).
      - One header row (header_rows=1).
      - Records headers + header_map for later validation/formatting passes.
      - Skips non-DataFrame entries.
      - Preserves domain meta in a hidden _meta sheet.
    """
    wb = WorkbookIR()

    for name, df in frames.items():
        # skip reserved frames and non-DataFrames
        if str(name) in _RESERVED_FRAME_KEYS:
            continue
        if not isinstance(df, pd.DataFrame):
            continue

        # sheet
        sh = wb.sheets.get(name)
        if sh is None:
            sh = SheetIR(name=str(name))
            wb.sheets[str(name)] = sh

        # headers and basic geometry
        headers = _flatten_header_to_strings(df)
        n_rows = int(df.shape[0]) + 1  # +1 for header row
        n_cols = int(df.shape[1])

        header_map = {col_name: idx + 1 for idx, col_name in enumerate(headers)}  # 1-based

        tbl = TableBlock(
            frame_name=str(name),
            top=1,
            left=1,
            header_rows=1,
            header_cols=1,
            n_rows=n_rows,
            n_cols=n_cols,
            headers=headers,
            header_map=header_map,
        )
        sh.tables.append(tbl)

        # inject per-sheet options from meta (set by yaml_overrides / bootstrap_meta)
        if meta:
            sheet_opts = (meta.get("sheets") or {}).get(str(name))
            if isinstance(sheet_opts, dict) and sheet_opts:
                sh.meta.setdefault("options", {}).update(sheet_opts)

    # stash the domain meta so meta_pass can persist it (unchanged from your version)
    if meta:
        meta_sheet = wb.hidden_sheets.setdefault("_meta", SheetIR(name="_meta"))
        meta_sheet.meta["workbook_meta_blob"] = meta

    return wb
