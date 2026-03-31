from __future__ import annotations
from warnings import warn
from .errors import DeprecatedAdapterError

# Re-export kept for one deprecation cycle so existing imports don't crash immediately.
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend  # re-export

__all__ = ["ExcelBackend"]

warn(
    "spreadsheet_handling.io_backends.excel_xlsxwriter is deprecated; "
    "import ExcelBackend from spreadsheet_handling.io_backends.xlsx.xlsx_backend instead.",
    DeprecationWarning,
    stacklevel=2,
)


def _raise() -> None:
    raise DeprecatedAdapterError(
        "xlsxwriter",
        "Import ExcelBackend from spreadsheet_handling.io_backends.xlsx.xlsx_backend.",
    )
