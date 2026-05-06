from .base import BackendBase, BackendOptions
from .csv_backend import CSVBackend
from .json_backend import JSONBackend
from .xml_backend import XMLBackend
from .errors import DeprecatedAdapterError
from .spreadsheet_contract import SpreadsheetParser, SpreadsheetRenderer


_BACKEND_SPECS = {
    'xlsx': ('spreadsheet_handling.io_backends.xlsx.xlsx_backend', 'ExcelBackend'),
    'ods': ('spreadsheet_handling.io_backends.ods.ods_backend', 'OdsBackend'),
    'csv': CSVBackend,
    'json': JSONBackend,
    'xml': XMLBackend,
    # aliases:
    'excel': ('spreadsheet_handling.io_backends.xlsx.xlsx_backend', 'ExcelBackend'),
    'calc': ('spreadsheet_handling.io_backends.ods.ods_backend', 'OdsBackend'),
}

_EXPORT_SPECS = {
    'ExcelBackend': ('spreadsheet_handling.io_backends.xlsx.xlsx_backend', 'ExcelBackend'),
    'OdsBackend': ('spreadsheet_handling.io_backends.ods.ods_backend', 'OdsBackend'),
}


def _resolve_spec(spec):
    if isinstance(spec, tuple):
        from importlib import import_module

        module_name, attr_name = spec
        return getattr(import_module(module_name), attr_name)
    return spec


def make_backend(kind: str) -> BackendBase:
    try:
        backend_cls = _resolve_spec(_BACKEND_SPECS[kind.lower()])
    except KeyError:
        raise ValueError(f"Unknown backend: {kind}. Available: {', '.join(sorted(_BACKEND_SPECS))}")
    return backend_cls()


def __getattr__(name: str):
    if name in _EXPORT_SPECS:
        value = _resolve_spec(_EXPORT_SPECS[name])
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'BackendBase',
    'BackendOptions',
    'CSVBackend',
    'DeprecatedAdapterError',
    'ExcelBackend',
    'JSONBackend',
    'OdsBackend',
    'SpreadsheetParser',
    'SpreadsheetRenderer',
    'XMLBackend',
    'make_backend',
]
