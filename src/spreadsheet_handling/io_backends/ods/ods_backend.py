from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Any, Dict, Final

import pandas as pd

from spreadsheet_handling.io_backends.base import (
    BackendBase,
    BackendOptions,
    coerce_backend_options,
)
from spreadsheet_handling.io_backends.ods.odf_parser import parse_workbook
from spreadsheet_handling.io_backends.ods.odf_renderer import render_workbook
from spreadsheet_handling.io_backends.spreadsheet_contract import (
    build_spreadsheet_render_plan,
    read_spreadsheet_frames,
)


log = logging.getLogger("sheets.ods")

_RESERVED_FRAME_KEYS: Final[set[str]] = {"_meta"}


class OdsBackend(BackendBase):
    """ODS adapter using the spreadsheet backend contract."""

    def write_multi(
        self,
        frames: dict[str, pd.DataFrame],
        path: str,
        options=None,
    ) -> None:
        out_path = Path(path).with_suffix(".ods")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        meta = (frames.get("_meta") if isinstance(frames, dict) else {}) or getattr(frames, "meta", {}) or {}
        plan = build_spreadsheet_render_plan(frames, meta)
        render_workbook(plan, out_path)

    def read_multi(
        self,
        path: str,
        header_levels: int,
        options: BackendOptions | None = None,
    ) -> Dict[str, pd.DataFrame]:
        """Read all visible sheets from an ODS file via the backend contract.

        GX-4 opt-in: ``options.extra["exact_header_depths"]`` (a sheet-name ->
        configured-depth mapping) selects exact multi-row header reads for the
        named sheets, mirroring the XLSX backend. Absent it, reads are
        byte-identical to before.
        """
        parser = _parser_for_options(options)
        return read_spreadsheet_frames(Path(path), parser=parser)


def _parser_for_options(options: BackendOptions | Any | None):
    """Return the workbook parser, honouring an opt-in exact-header-depth map.

    Reads ``exact_header_depths`` from ``options.extra`` (BackendOptions) or from
    a plain options mapping. Absent, the unmodified ``parse_workbook`` is used, so
    ordinary reads are byte-identical. Mirrors the XLSX backend seam.
    """
    if options is None:
        return parse_workbook
    opts = coerce_backend_options(options)
    if isinstance(opts, BackendOptions):
        extra = opts.extra or {}
    elif isinstance(opts, dict):
        extra = opts.get("extra") if isinstance(opts.get("extra"), dict) else opts
    else:
        extra = {}
    depths = extra.get("exact_header_depths") if isinstance(extra, dict) else None
    if not depths:
        return parse_workbook
    return functools.partial(parse_workbook, exact_header_depths=depths)


def save_ods(
    frames: Dict[str, Any],
    path: str,
    options: BackendOptions | None = None,
) -> None:
    sanitized: Dict[str, Any] = {}

    meta_attr = getattr(frames, "meta", None)
    if isinstance(frames, dict) and "_meta" in frames:
        sanitized["_meta"] = frames["_meta"]
    elif meta_attr is not None:
        sanitized["_meta"] = meta_attr

    for name, df in frames.items():
        name_str = str(name)
        if name_str in _RESERVED_FRAME_KEYS:
            sanitized[name_str] = df
            continue
        sanitized[name_str] = _ensure_dataframe(df)

    OdsBackend().write_multi(sanitized, path, options=options)


def load_ods(
    path: str,
    options: BackendOptions | None = None,
    *,
    header_levels: int = 1,
) -> Dict[str, pd.DataFrame]:
    return OdsBackend().read_multi(path, header_levels=header_levels, options=options)


def _ensure_dataframe(obj: Any) -> pd.DataFrame:
    if isinstance(obj, pd.DataFrame):
        return obj
    return pd.DataFrame(obj)


__all__ = ["OdsBackend", "save_ods", "load_ods"]
