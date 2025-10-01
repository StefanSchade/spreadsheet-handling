from __future__ import annotations

from typing import Dict, Type

from .base import BackendBase
from .json_backend import JSONBackend
from .xlsx_backend import ExcelBackend
# Optional: if/when you add YAML/CSV/ODS, import and register them here.


# Registry of available backends keyed by "kind"
_BACKENDS: Dict[str, Type[BackendBase]] = {
    "json": JSONBackend,
    "xlsx": ExcelBackend,
    # "yaml": YAMLBackend,
    # "csv": CSVBackend,
    # "ods": OdsBackend,
}


def make_backend(kind: str) -> BackendBase:
    """
    Factory returning an instance of the requested backend.

    Parameters
    ----------
    kind : str
        Short identifier used in config/CLI (e.g., 'json', 'xlsx').

    Returns
    -------
    BackendBase
        Fresh instance of the backend.

    Raises
    ------
    KeyError
        If `kind` is unknown.
    """
    k = (kind or "").strip().lower()
    cls = _BACKENDS.get(k)
    if cls is None:
        available = ", ".join(sorted(_BACKENDS))
        raise KeyError(f"Unknown backend kind '{kind}'. Available: {available}")
    return cls()
