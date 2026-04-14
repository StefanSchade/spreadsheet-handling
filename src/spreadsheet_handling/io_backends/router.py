from __future__ import annotations

from typing import Callable, Dict

import pandas as pd

from .csv_backend import load_csv_dir, save_csv_dir
from .json_backend import read_json_dir, write_json_dir
from .ods.ods_backend import load_ods, save_ods
from .xml_backend import read_xml_dir, write_xml_dir
from .yaml_backend import load_yaml_dir, save_yaml_dir
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import load_xlsx, save_xlsx

Frames = dict[str, pd.DataFrame]

LOADERS: Dict[str, Callable[..., Frames]] = {
    "csv_dir": load_csv_dir,
    "ods": load_ods,
    "calc": load_ods,
    "xlsx": load_xlsx,
    "json_dir": read_json_dir,
    "json": read_json_dir,
    "yaml_dir": load_yaml_dir,
    "yaml": load_yaml_dir,
    "xml_dir": read_xml_dir,
    "xml": read_xml_dir,
}

SAVERS: Dict[str, Callable[..., None]] = {
    "csv_dir": save_csv_dir,
    "ods": save_ods,
    "calc": save_ods,
    "xlsx": save_xlsx,
    "json_dir": write_json_dir,
    "json": write_json_dir,
    "yaml_dir": save_yaml_dir,
    "yaml": save_yaml_dir,
    "xml_dir": write_xml_dir,
    "xml": write_xml_dir,
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
