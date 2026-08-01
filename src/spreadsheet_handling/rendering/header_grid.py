"""Backend-neutral exact multi-row header grid helpers (GX-3a import path).

The implementation now lives in ``core.header_grid`` (leaf, importable by both
``rendering`` and ``domain``); this module re-exports it so the established GX-3a
``rendering.header_grid`` import path is unchanged. See ``core.header_grid`` for
the contract and the GX-3b reason the helper moved to ``core``.
"""
from __future__ import annotations

from spreadsheet_handling.core.header_grid import HeaderGrid, forward_fill_header_grid

__all__ = ["HeaderGrid", "forward_fill_header_grid"]
