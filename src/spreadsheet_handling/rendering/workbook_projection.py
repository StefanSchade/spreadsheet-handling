from __future__ import annotations

"""Project spreadsheet-generic ``WorkbookIR`` data back into frames independent of concrete spreadsheet backends."""

import ast
import json
from typing import Any, Mapping

from .ir import WorkbookIR


CARRIER_BLOB_KEY = "workbook_meta_blob"


def _try_parse_blob(value: Any) -> dict[str, Any] | None:
    """Best-effort parse of a hidden-sheet carrier blob string into a dict.

    Accepts the canonical JSON form first and falls back to the legacy
    pre-JSON ``repr`` form. Returns ``None`` for anything that does not
    decode to a dict so callers can ignore unparseable input.
    """
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if parsed is None:
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError, TypeError):
            return None
    return parsed if isinstance(parsed, dict) else None


def canonicalize_workbook_meta(meta: Mapping[str, Any] | None) -> dict[str, Any]:
    """Strip any nested ``workbook_meta_blob`` carrier wrapper from ``meta``.

    The key ``workbook_meta_blob`` is a hidden-sheet carrier convention --
    the first cell of the hidden ``_meta`` sheet -- not part of the
    canonical workbook meta contract. If a mapping arrives carrying it
    (e.g. a malformed read-back where the sheet rows were serialised as
    the new blob, or a re-export that fed a sheet-level representation
    back into the writer), this helper unwraps the nested blob so the
    canonical top-level content (``workbook_view``, ``sheets``,
    ``legend_blocks``, ...) is restored.

    Inner canonical content wins over the outer sheet-level wrapper. The
    helper is recursive so chained wrappings collapse to a single
    canonical mapping. It is a no-op for already-canonical mappings.
    """
    if not isinstance(meta, Mapping):
        return {}

    outer = dict(meta)
    if CARRIER_BLOB_KEY not in outer:
        return outer

    blob_value = outer.pop(CARRIER_BLOB_KEY)
    parsed = _try_parse_blob(blob_value)
    if parsed is None:
        return outer

    merged = dict(parsed)
    for key, value in outer.items():
        merged.setdefault(key, value)
    return canonicalize_workbook_meta(merged)


def _hidden_meta_to_frames_meta(meta_sh: Any) -> dict[str, Any] | None:
    blob = meta_sh.meta.get(CARRIER_BLOB_KEY, "")
    meta_dict = _try_parse_blob(blob) if blob else None
    if meta_dict is not None:
        return canonicalize_workbook_meta(meta_dict)
    kv = {k: v for k, v in meta_sh.meta.items() if k != "_hidden"}
    if not kv:
        return None
    return canonicalize_workbook_meta(kv)


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
        meta = _hidden_meta_to_frames_meta(meta_sh)
        if meta is not None:
            frames["_meta"] = meta

    return frames


__all__ = ["CARRIER_BLOB_KEY", "canonicalize_workbook_meta", "workbookir_to_frames"]
