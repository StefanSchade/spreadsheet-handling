from __future__ import annotations
from warnings import warn
from .xlsx_backend import ExcelBackend  # re-export

__all__ = ["ExcelBackend"]

warn(
    "spreadsheet_handling.io_backends.excel_xlsxwriter is deprecated; use xlsx_backend",
    DeprecationWarning,
    stacklevel=2,
)
