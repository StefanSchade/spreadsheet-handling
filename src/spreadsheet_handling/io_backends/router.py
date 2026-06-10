from __future__ import annotations

from importlib import import_module
from typing import Callable, Dict

import pandas as pd

from .base import BackendBase
from .csv_backend import CSVBackend, load_csv_dir, save_csv_dir
from .discard_backend import save_discard
from .json_backend import JSONBackend, read_json_dir, write_json_dir
from .xml_backend import XMLBackend, read_xml_dir, write_xml_dir
from .yaml_backend import load_yaml_dir, save_yaml_dir

Frames = dict[str, pd.DataFrame]
BackendFactory = Callable[[], BackendBase]
BackendSpec = BackendFactory | tuple[str, str]


def _lazy_callable(module_name: str, attr_name: str) -> Callable:
    def _call(*args, **kwargs):
        return getattr(import_module(module_name), attr_name)(*args, **kwargs)

    _call.__name__ = attr_name
    return _call


def _resolve_backend_spec(spec: BackendSpec) -> BackendFactory:
    if isinstance(spec, tuple):
        module_name, attr_name = spec
        return getattr(import_module(module_name), attr_name)
    return spec


LOADERS: Dict[str, Callable[..., Frames]] = {
    "csv_dir": load_csv_dir,
    "ods": _lazy_callable("spreadsheet_handling.io_backends.ods.ods_backend", "load_ods"),
    "calc": _lazy_callable("spreadsheet_handling.io_backends.ods.ods_backend", "load_ods"),
    "xlsx": _lazy_callable("spreadsheet_handling.io_backends.xlsx.xlsx_backend", "load_xlsx"),
    "json_dir": read_json_dir,
    "json": read_json_dir,
    "yaml_dir": load_yaml_dir,
    "yaml": load_yaml_dir,
    "xml_dir": read_xml_dir,
    "xml": read_xml_dir,
}

SAVERS: Dict[str, Callable[..., None]] = {
    "csv_dir": save_csv_dir,
    "discard": save_discard,
    "ods": _lazy_callable("spreadsheet_handling.io_backends.ods.ods_backend", "save_ods"),
    "calc": _lazy_callable("spreadsheet_handling.io_backends.ods.ods_backend", "save_ods"),
    "xlsx": _lazy_callable("spreadsheet_handling.io_backends.xlsx.xlsx_backend", "save_xlsx"),
    "json_dir": write_json_dir,
    "json": write_json_dir,
    "yaml_dir": save_yaml_dir,
    "yaml": save_yaml_dir,
    "xml_dir": write_xml_dir,
    "xml": write_xml_dir,
}

BACKENDS: Dict[str, BackendSpec] = {
    "xlsx": ("spreadsheet_handling.io_backends.xlsx.xlsx_backend", "ExcelBackend"),
    "excel": ("spreadsheet_handling.io_backends.xlsx.xlsx_backend", "ExcelBackend"),
    "ods": ("spreadsheet_handling.io_backends.ods.ods_backend", "OdsBackend"),
    "calc": ("spreadsheet_handling.io_backends.ods.ods_backend", "OdsBackend"),
    "csv": CSVBackend,
    "json": JSONBackend,
    "xml": XMLBackend,
}


def get_loader(kind: str) -> Callable[..., Frames]:
    fn = LOADERS.get(kind)
    if fn is None:
        raise ValueError(f"Unknown loader kind: {kind}")
    return fn


def get_saver(kind: str) -> Callable[..., None]:
    fn = SAVERS.get(kind)
    if fn is None:
        raise ValueError(f"Unknown saver kind: {kind}")
    return fn


def get_backend_factory(kind: str) -> BackendFactory:
    normalized = kind.lower()
    spec = BACKENDS.get(normalized)
    if spec is None:
        raise ValueError(f"Unknown backend: {kind}. Available: {', '.join(sorted(BACKENDS))}")
    return _resolve_backend_spec(spec)
