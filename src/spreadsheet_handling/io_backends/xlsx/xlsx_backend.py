from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Final

import pandas as pd

from spreadsheet_handling.io_backends.base import BackendBase, BackendOptions
from spreadsheet_handling.io_backends.spreadsheet_contract import (
    build_spreadsheet_render_plan,
    read_spreadsheet_frames,
)
from spreadsheet_handling.io_backends.xlsx.openpyxl_parser import parse_workbook
from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook


log = logging.getLogger('sheets.xlsx')

_RESERVED_FRAME_KEYS: Final[set[str]] = {'_meta'}   # extend here if we add more internals


class ExcelBackend(BackendBase):
    """XLSX adapter using the spreadsheet backend contract."""

    def write_multi(
        self,
        frames: dict[str, pd.DataFrame],
        path: str,
        options=None,
    ) -> None:
        out_path = Path(path).with_suffix('.xlsx')
        out_path.parent.mkdir(parents=True, exist_ok=True)

        meta = (frames.get('_meta') if isinstance(frames, dict) else {}) or getattr(frames, 'meta', {}) or {}
        # Keep only the XLSX-specific entry layer here. The spreadsheet-generic
        # compose/pass/plan orchestration lives in spreadsheet_contract so
        # future spreadsheet adapters can reuse it instead of duplicating it.
        plan = build_spreadsheet_render_plan(frames, meta)
        render_workbook(plan, out_path)

    def read_multi(
        self,
        path: str,
        header_levels: int,
        options: BackendOptions | None = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Read all visible sheets from an XLSX file via the spreadsheet backend contract.

        Hidden sheets (e.g. ``_meta``) are excluded from data frames.
        If a ``_meta`` sheet is present its key/value pairs are extracted
        and returned as ``frames["_meta"]`` (a plain dict, not a DataFrame).
        """
        return read_spreadsheet_frames(Path(path), parser=parse_workbook)


def save_xlsx(
    frames: Dict[str, Any],
    path: str,
    options: BackendOptions | None = None,
) -> None:
    """
    Preserve meta under '_meta' (either from frames['_meta'] or frames.meta)
    so the writer can apply spreadsheet semantics; coerce all sheets to DataFrames.
    """
    sanitized: Dict[str, Any] = {}

    meta_attr = getattr(frames, 'meta', None)
    if isinstance(frames, dict) and '_meta' in frames:
        sanitized['_meta'] = frames['_meta']
    elif meta_attr is not None:
        sanitized['_meta'] = meta_attr

    for name, df in frames.items():
        name_str = str(name)
        if name_str in _RESERVED_FRAME_KEYS:
            sanitized[name_str] = df
            continue
        df0 = _ensure_dataframe(df)
        sanitized[name_str] = df0

    ExcelBackend().write_multi(sanitized, path, options=options)


def load_xlsx(
    path: str,
    options: BackendOptions | None = None,
) -> Dict[str, pd.DataFrame]:
    """Router-facing reader: read all sheets, assume single header row."""
    return ExcelBackend().read_multi(path, header_levels=1, options=options)


def _ensure_dataframe(obj: Any) -> pd.DataFrame:
    """Coerce various tabular shapes to a DataFrame."""
    if isinstance(obj, pd.DataFrame):
        return obj
    return pd.DataFrame(obj)


def write_xlsx(
    path: str,
    frames: Dict[str, pd.DataFrame],
    meta: Any,
    ctx: Any,
) -> None:
    """Test-facing convenience used by unit tests."""
    ExcelBackend().write_multi(frames, path, options=None)


__all__ = ['ExcelBackend', 'save_xlsx', 'load_xlsx']
