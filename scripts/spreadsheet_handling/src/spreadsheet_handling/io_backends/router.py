from __future__ import annotations

from typing import Callable, Dict
import pandas as pd

Frames = dict[str, pd.DataFrame]

# CSV directory backend (present in your repo/tests)
try:
    from .csv_backend import load_csv_dir as _load_csv_dir, save_csv_dir as _save_csv_dir
except Exception:  # pragma: no cover
    _load_csv_dir = None  # type: ignore[assignment]
    _save_csv_dir = None  # type: ignore[assignment]

# XLSX backend (present in your repo as xlsx_backend)
try:
    from .xlsx_backend import load_xlsx as _load_xlsx, save_xlsx as _save_xlsx
except Exception:  # pragma: no cover
    _load_xlsx = None  # type: ignore[assignment]
    _save_xlsx = None  # type: ignore[assignment]

# JSON/YAML backends are optional; register when you add them
try:
    from .json_backend import load_json_dir as _load_json_dir, save_json_dir as _save_json_dir  # noqa: F401
except Exception:  # pragma: no cover
    _load_json_dir = None  # type: ignore[assignment]
    _save_json_dir = None  # type: ignore[assignment]

try:
    from .yaml_backend import load_yaml_dir as _load_yaml_dir, save_yaml_dir as _save_yaml_dir  # noqa: F401
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

if _load_csv_dir and _save_csv_dir:
    LOADERS["csv_dir"] = _load_csv_dir
    SAVERS["csv_dir"] = _save_csv_dir

if _load_xlsx and _save_xlsx:
    LOADERS["xlsx"] = _load_xlsx
    SAVERS["xlsx"] = _save_xlsx

if _load_json_dir and _save_json_dir:
    LOADERS["json_dir"] = _load_json_dir
    SAVERS["json_dir"] = _save_json_dir

if _load_yaml_dir and _save_yaml_dir:
    LOADERS["yaml_dir"] = _load_yaml_dir
    SAVERS["yaml_dir"] = _save_yaml_dir


def get_loader(kind: str) -> Callable[[str], Frames]:
    fn = LOADERS.get(kind)
    _require(fn, kind, "read")
    return fn  # type: ignore[return-value]


def get_saver(kind: str) -> Callable[[Frames, str], None]:
    fn = SAVERS.get(kind)
    _require(fn, kind, "write")
    return fn  # type: ignore[return-value]
