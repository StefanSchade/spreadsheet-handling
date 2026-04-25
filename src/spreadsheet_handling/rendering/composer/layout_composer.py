from __future__ import annotations
from typing import Dict, Mapping, Any
import pandas as pd

from ..ir import WorkbookIR, SheetIR, TableBlock

_RESERVED_FRAME_KEYS = {"_meta"}  # extend as needed
_WORKBOOK_OPTION_KEYS = {
    "freeze_header",
    "auto_filter",
    "header_fill_rgb",
    "helper_fill_rgb",
    "helper_prefix",
}

_LEGEND_BASE_COLUMNS = ("token", "label")
_LEGEND_OPTIONAL_COLUMNS = ("group", "description")
_LEGEND_COLUMN_LABELS = {
    "token": "Token",
    "label": "Meaning",
    "group": "Group",
    "description": "Description",
}


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


def _legend_items(meta: Dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    if not meta:
        return []
    raw = meta.get("legend_blocks")
    if not raw:
        return []
    if isinstance(raw, dict):
        return [
            (str(name), spec)
            for name, spec in raw.items()
            if isinstance(spec, dict)
        ]
    if isinstance(raw, list):
        items: list[tuple[str, dict[str, Any]]] = []
        for index, spec in enumerate(raw, start=1):
            if not isinstance(spec, dict):
                continue
            name = str(spec.get("name") or spec.get("id") or f"legend_{index}")
            items.append((name, spec))
        return items
    raise ValueError("legend_blocks must be a mapping or a list of mappings")


def _legend_columns(entries: list[dict[str, Any]]) -> list[str]:
    columns = list(_LEGEND_BASE_COLUMNS)
    for column in _LEGEND_OPTIONAL_COLUMNS:
        if any(entry.get(column) not in (None, "") for entry in entries):
            columns.append(column)
    return columns


def _validate_legend_entries(legend_name: str, entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"legend block {legend_name!r} requires a non-empty entries list")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"legend block {legend_name!r} entry {index} must be a mapping")

        raw_token = entry.get("token")
        token = "" if raw_token is None else str(raw_token)
        if not token.strip():
            raise ValueError(f"legend block {legend_name!r} entry {index} has an empty token")
        if token in seen:
            raise ValueError(f"legend block {legend_name!r} contains duplicate token {token!r}")
        seen.add(token)

        raw_label = entry.get("label")
        label = "" if raw_label is None else str(raw_label)
        if not label.strip():
            raise ValueError(f"legend block {legend_name!r} entry {index} has an empty label")

        normalized.append(dict(entry, token=token, label=label))

    return normalized


def _target_table_for_legend(
    sheet: SheetIR,
    *,
    target_name: str | None,
) -> TableBlock | None:
    if target_name:
        for table in sheet.tables:
            if table.frame_name == target_name:
                return table
        raise ValueError(f"legend target table {target_name!r} was not found on sheet {sheet.name!r}")
    return sheet.tables[0] if sheet.tables else None


def _resolve_legend_position(
    placement: Mapping[str, Any],
    target: TableBlock | None,
) -> tuple[int, int]:
    if "top" in placement and "left" in placement:
        return int(placement["top"]), int(placement["left"])

    if target is None:
        return 1, 1

    anchor = str(placement.get("anchor") or "right_of_table")
    if anchor == "below_table":
        return target.top + target.n_rows + 2, target.left
    if anchor == "right_of_table":
        return target.top, target.left + target.n_cols + 1
    raise ValueError(f"Unsupported legend placement anchor {anchor!r}")


def _add_legend_blocks(wb: WorkbookIR, meta: Dict[str, Any] | None) -> None:
    if not meta:
        return

    for legend_name, spec in _legend_items(meta):
        entries = _validate_legend_entries(legend_name, spec.get("entries"))
        placement = spec.get("placement") or {}
        if not isinstance(placement, Mapping):
            raise ValueError(f"legend block {legend_name!r} placement must be a mapping")

        sheet_name = str(
            placement.get("sheet")
            or spec.get("sheet")
            or placement.get("target")
            or spec.get("target")
            or legend_name
        )
        sheet = wb.sheets.setdefault(sheet_name, SheetIR(name=sheet_name))
        target_name = placement.get("target") or spec.get("target")
        target = _target_table_for_legend(
            sheet,
            target_name=str(target_name) if target_name else None,
        )
        top, left = _resolve_legend_position(placement, target)

        columns = _legend_columns(entries)
        headers = [_LEGEND_COLUMN_LABELS[column] for column in columns]
        data = [
            [entry.get(column, "") for column in columns]
            for entry in entries
        ]
        frame_name = f"legend_{legend_name}"
        table = TableBlock(
            frame_name=frame_name,
            kind="legend",
            title=str(spec.get("title") or legend_name),
            top=top,
            left=left,
            header_rows=1,
            header_cols=1,
            n_rows=len(data) + 1,
            n_cols=len(headers),
            headers=headers,
            header_map={header: idx + 1 for idx, header in enumerate(headers)},
            data=data,
        )
        sheet.tables.append(table)

        spec["resolved"] = {
            "kind": "legend",
            "sheet": sheet_name,
            "frame_name": frame_name,
            "top": top,
            "left": left,
            "n_rows": table.n_rows,
            "n_cols": table.n_cols,
        }

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
    workbook_options = {
        key: meta[key]
        for key in _WORKBOOK_OPTION_KEYS
        if meta and key in meta
    }

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
            data=df.values.tolist(),
        )
        sh.tables.append(tbl)
        sh.meta["__header_grid"] = header_grid
        if header_merges:
            sh.meta["__header_merges"] = header_merges

        # inject workbook and per-sheet options from meta
        options = dict(workbook_options)
        if meta:
            sheet_opts = (meta.get("sheets") or {}).get(str(name))
            if isinstance(sheet_opts, dict) and sheet_opts:
                options.update(sheet_opts)
        if options:
            sh.meta.setdefault("options", {}).update(options)

    _add_legend_blocks(wb, meta)

    # stash the domain meta so meta_pass can persist it (unchanged from your version)
    if meta:
        meta_sheet = wb.hidden_sheets.setdefault("_meta", SheetIR(name="_meta"))
        meta_sheet.meta["workbook_meta_blob"] = meta

    return wb
