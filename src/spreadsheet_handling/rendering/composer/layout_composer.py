from __future__ import annotations
from typing import Dict, Mapping, Any
import pandas as pd

from ..ir import WorkbookIR, SheetIR, TableBlock

_RESERVED_FRAME_KEYS = {"_meta"}  # extend as needed


def _build_header_grid_and_merges(df: pd.DataFrame) -> tuple[list[list[str]], list[tuple[int, int, int, int]], int]:
    """
    Build a row-wise header grid and merge regions for MultiIndex columns.

    Returns
    -------
    grid:
        2D list [header_row][col] with string labels.
    merges:
        Relative merge regions as (r1, c1, r2, c2), 1-based, relative to table top-left.
    header_rows:
        Number of header rows.
    """
    if not isinstance(df.columns, pd.MultiIndex):
        headers = [str(c) for c in df.columns.tolist()]
        return [headers], [], 1

    tuples = [tuple("" if x is None else str(x) for x in t) for t in df.columns.tolist()]
    n_cols = len(tuples)
    n_levels = int(df.columns.nlevels)
    grid = [[tuples[c][lvl] for c in range(n_cols)] for lvl in range(n_levels)]
    merges: list[tuple[int, int, int, int]] = []

    # Horizontal merges for equal consecutive labels in same header row.
    for r, row_vals in enumerate(grid, start=1):
        c = 1
        while c <= n_cols:
            label = row_vals[c - 1]
            if not label:
                c += 1
                continue
            c2 = c
            while c2 + 1 <= n_cols and row_vals[c2] == label:
                c2 += 1
            if c2 > c:
                merges.append((r, c, r, c2))
            c = c2 + 1

    # Vertical merges where lower header levels are empty for the same column.
    for c in range(1, n_cols + 1):
        r = 1
        while r <= n_levels:
            label = grid[r - 1][c - 1]
            if not label:
                r += 1
                continue
            r2 = r
            while r2 + 1 <= n_levels and grid[r2][c - 1] == "":
                r2 += 1
            if r2 > r:
                merges.append((r, c, r2, c))
            r = r2 + 1

    return grid, merges, n_levels

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
      - Header rows dynamically set from MultiIndex column levels
        (1 for single-level, N for N-level MultiIndex).
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
        header_grid, header_merges, header_rows = _build_header_grid_and_merges(df)
        n_rows = int(df.shape[0]) + header_rows
        n_cols = int(df.shape[1])

        header_map = {col_name: idx + 1 for idx, col_name in enumerate(headers)}  # 1-based

        tbl = TableBlock(
            frame_name=str(name),
            top=1,
            left=1,
            header_rows=header_rows,
            header_cols=1,
            n_rows=n_rows,
            n_cols=n_cols,
            headers=headers,
            header_map=header_map,
        )
        sh.tables.append(tbl)
        sh.meta["__header_grid"] = header_grid
        if header_merges:
            sh.meta["__header_merges"] = header_merges

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
