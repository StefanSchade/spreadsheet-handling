from __future__ import annotations
from typing import Callable, Dict
import pandas as pd

Frames = dict[str, pd.DataFrame]

# CSV directory backend
try:
    from .csv_backend import load_csv_dir as _load_csv_dir, save_csv_dir as _save_csv_dir
except Exception:  # pragma: no cover
    _load_csv_dir = None  # type: ignore[assignment]
    _save_csv_dir = None  # type: ignore[assignment]

# XLSX backend
try:
    from .xlsx_backend import load_xlsx as _load_xlsx, save_xlsx as _save_xlsx
except Exception:  # pragma: no cover
    _load_xlsx = None  # type: ignore[assignment]
    _save_xlsx = None  # type: ignore[assignment]

# JSON backend
try:
    from .json_backend import read_json_dir as _load_json_dir, write_json_dir as _save_json_dir
except Exception:  # pragma: no cover
    _load_json_dir = None  # type: ignore[assignment]
    _save_json_dir = None  # type: ignore[assignment]

# YAML backend
try:
    from .yaml_backend import load_yaml_dir as _load_yaml_dir, save_yaml_dir as _save_yaml_dir
except Exception:  # pragma: no cover
    _load_yaml_dir = None  # type: ignore[assignment]
    _save_yaml_dir = None  # type: ignore[assignment]


def _require(fn: object, kind: str, rw: str) -> None:
    if fn is None:
        raise SystemExit(
            f"I/O backend for '{kind}' ({rw}) is not available. "
            f"Ensure the module exists and is importable."
        )


LOADERS: Dict[str, Callable[[str], Frames]] = {}
SAVERS: Dict[str, Callable[[Frames, str], None]] = {}

# CSV
if _load_csv_dir and _save_csv_dir:
    LOADERS["csv_dir"] = _load_csv_dir
    SAVERS["csv_dir"] = _save_csv_dir

# XLSX
if _load_xlsx and _save_xlsx:
    LOADERS["xlsx"] = _load_xlsx
    SAVERS["xlsx"] = _save_xlsx

# JSON (register both 'json_dir' and 'json')
if _load_json_dir and _save_json_dir:
    for alias in ("json_dir", "json"):
        LOADERS[alias] = _load_json_dir
        SAVERS[alias] = _save_json_dir

# YAML (register both 'yaml_dir' and 'yaml')
if _load_yaml_dir and _save_yaml_dir:
    for alias in ("yaml_dir", "yaml"):
        LOADERS[alias] = _load_yaml_dir
        SAVERS[alias] = _save_yaml_dir


def get_loader(kind: str) -> Callable[[str], Frames]:
    fn = LOADERS.get(kind)
    _require(fn, kind, "read")
    return fn  # type: ignore[return-value]


def get_saver(kind: str) -> Callable[[Frames, str], None]:
    fn = SAVERS.get(kind)
    _require(fn, kind, "write")
    return fn  # type: ignore[return-value]
