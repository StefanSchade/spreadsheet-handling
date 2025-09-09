from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import pandas as pd


@dataclass
class BackendOptions:
    """
    Backend-übergreifende, semantikarme Schalter.
    Backends dürfen Felder ignorieren, die für sie nicht relevant sind.

    - levels:      gewünschte Header-Ebenen beim (Re-)Anheben des Headers
    - helper_prefix: Prefix für Helper-Spalten (nur für Export-Policy/Filter relevant)
    - drop_helpers_on_export: Backend-spezifische Export-Policy (z.B. JSON: True)
    - encoding:    z.B. für CSV/JSON (falls Backend das nutzt)
    - extra:       Escape-Hatch für experimentelle/Backend-spezifische Flags
    """
    levels: Optional[int] = None
    helper_prefix: str = "_"
    drop_helpers_on_export: Optional[bool] = None
    encoding: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class BackendBase:
    def write(
        self,
        df: pd.DataFrame,
        path: str,
        sheet_name: str = "Daten",
        options: Optional[BackendOptions] = None,
    ) -> None:
        raise NotImplementedError

    def read(
        self,
        path: str,
        header_levels: int,
        sheet_name: Optional[str] = None,
        options: Optional[BackendOptions] = None,
    ) -> pd.DataFrame:
        raise NotImplementedError

    # optionale Multi-Sheet API (Default passt für Workbook-Backends;
    # CSV/JSON-Backends überschreiben i.d.R. diese Methode)
    def write_multi(
        self,
        sheets: dict[str, pd.DataFrame],
        path: str,
        options: BackendOptions | None = None,
    ) -> None:
        for name, df in sheets.items():
            # Wenn das konkrete Backend 'options' nicht kennt, fallback ohne options:
            try:
                self.write(df, path, sheet_name=name, options=options)
            except TypeError:
                self.write(df, path, sheet_name=name)

    def read_multi(
        self,
        path: str,
        header_levels: int,
        options: BackendOptions | None = None,
    ) -> dict[str, pd.DataFrame]:
        # Default: 1 Sheet namens "Daten" – echte Multi-Sheet-Backends überschreiben.
        try:
            df = self.read(path, header_levels, sheet_name="Daten", options=options)
        except TypeError:
            df = self.read(path, header_levels, sheet_name="Daten")
        return {"Daten": df}

