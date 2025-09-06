from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from .engine import Engine
from .cli.sheets_pack import run_pack as pack  # bequemer Kurzname

try:
    __version__ = version("spreadsheet_handling")
except PackageNotFoundError:
    __version__ = "0.0.dev"

__all__ = ["__version__", "Engine", "pack"]

