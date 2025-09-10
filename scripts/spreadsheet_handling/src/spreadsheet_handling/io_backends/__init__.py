from .base import BackendBase, BackendOptions
from .csv_backend import CSVBackend
from .xlsx_backend import ExcelBackend
from .json_backend import JSONBackend


_BACKENDS = {
    "xlsx": ExcelBackend,
    "csv": CSVBackend,
    "json": JSONBackend,
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
    "make_backend",
]
