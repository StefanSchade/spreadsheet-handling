from __future__ import annotations

"""Project spreadsheet-generic ``WorkbookIR`` data back into frames independent of concrete spreadsheet backends."""

import ast
import json
from typing import Any

from .ir import WorkbookIR


def workbookir_to_frames(ir: WorkbookIR) -> dict[str, Any]:
    """
    Convert a :class:`WorkbookIR` into a frames dict suitable for the pipeline.

    Each visible sheet's first table becomes a DataFrame.
    Hidden ``_meta`` sheet is returned as ``frames["_meta"]`` (plain dict).
    """
    import pandas as pd

    frames: dict[str, Any] = {}

    for name, sh in ir.sheets.items():
        if not sh.tables:
            frames[name] = pd.DataFrame()
            continue
        tbl = sh.tables[0]
        data = tbl.data if tbl.data is not None else []

        if tbl.header_rows > 1 and tbl.headers and " / " in tbl.headers[0]:
            tuples = [tuple(h.split(" / ")) for h in tbl.headers]
            columns = pd.MultiIndex.from_tuples(tuples)
        else:
            columns = tbl.headers or []

        df = pd.DataFrame(data, columns=columns)
        df = df.where(pd.notnull(df), "")
        frames[name] = df

    meta_sh = ir.hidden_sheets.get("_meta")
    if meta_sh:
        blob = meta_sh.meta.get("workbook_meta_blob", "")
        if blob:
            try:
                meta_dict = json.loads(blob)
                if isinstance(meta_dict, dict):
                    frames["_meta"] = meta_dict
            except (json.JSONDecodeError, TypeError):
                pass
            if "_meta" not in frames:
                try:
                    meta_dict = ast.literal_eval(blob)
                    if isinstance(meta_dict, dict):
                        frames["_meta"] = meta_dict
                except (ValueError, SyntaxError):
                    pass
        if "_meta" not in frames:
            kv = {k: v for k, v in meta_sh.meta.items() if k != "_hidden"}
            if kv:
                frames["_meta"] = kv

    return frames


__all__ = ["workbookir_to_frames"]
