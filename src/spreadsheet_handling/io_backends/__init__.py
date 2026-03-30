from .base import BackendBase, BackendOptions
from .csv_backend import CSVBackend
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from .json_backend import JSONBackend
from .xml_backend import XMLBackend


_BACKENDS = {
    "xlsx": ExcelBackend,
    "csv": CSVBackend,
    "json": JSONBackend,
    "xml": XMLBackend,
    # aliases:
    "excel": ExcelBackend,
}

def make_backend(kind: str) -> BackendBase:
    try:
        return _BACKENDS[kind.lower()]()
    except KeyError:
        raise ValueError(f"Unknown backend: {kind}. Available: {', '.join(sorted(_BACKENDS))}")

__all__ = [
    "BackendBase",
    "BackendOptions",
    "CSVBackend",
    "ExcelBackend",
    "JSONBackend",
    "XMLBackend",
    "make_backend",
]
