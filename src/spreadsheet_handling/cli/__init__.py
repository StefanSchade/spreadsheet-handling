# src/spreadsheet_handling/cli/__init__.py
from __future__ import annotations
from typing import Any

__all__ = ["pack", "unpack", "run"]

def __getattr__(name: str) -> Any:
    if name == "pack":
        from .sheets_pack import run_pack
        return run_pack
    if name == "unpack":
        from .sheets_unpack import run_unpack
        return run_unpack
    if name == "run":
        from . import run as run_mod
        return run_mod
    raise AttributeError(name)
