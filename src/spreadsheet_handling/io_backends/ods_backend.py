from __future__ import annotations
import pandas as pd
from .base import BackendBase, BackendOptions
from .errors import DeprecatedAdapterError

_HINT = "Use XLSX (ExcelBackend) or JSON (JSONBackend) instead."


class ODSBackend(BackendBase):
    """Deprecated stub. ODS support was never implemented."""

    def write(self, df: pd.DataFrame, path: str, sheet_name: str = "Daten",
              options: BackendOptions | None = None) -> None:
        raise DeprecatedAdapterError("ods", _HINT)

    def read(self, path: str, header_levels: int, sheet_name: str = "Daten",
             options: BackendOptions | None = None) -> pd.DataFrame:
        raise DeprecatedAdapterError("ods", _HINT)
