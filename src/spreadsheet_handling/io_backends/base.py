from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd


@dataclass
class BackendOptions:
    """
    Gemeinsame, optionale IO-Policies.
    - levels: gewünschte Header-Ebenen beim Lesen/Schreiben (falls relevant)
    - helper_prefix: Prefix von Helper-Spalten (nur für Export-Policy)
    - drop_helper_columns: beim Schreiben Helper-Spalten verwerfen (z.B. JSON-Export)
    - extras: backend-spezifische Ergänzungen, ohne die Signatur zu sprengen
    """

    levels: int | None = None
    helper_prefix: str = "_"
    drop_helpers_on_export: bool | None = None
    encoding: str | None = None
    extra: Dict[str, Any] = field(default_factory=dict)


class BackendBase:
    def write(
        self,
        df: pd.DataFrame,
        path: str,
        sheet_name: str = "Daten",
        options: BackendOptions | None = None,
    ) -> None:
        raise NotImplementedError

    def read(
        self,
        path: str,
        header_levels: int,
        sheet_name: str | None = None,
        options: BackendOptions | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError

    def write_multi(
        self,
        sheets: dict[str, pd.DataFrame],
        path: str,
        options: BackendOptions | None = None,
    ) -> None:
        for name, df in sheets.items():
            try:
                self.write(df, path, sheet_name=name, options=options)
            except TypeError:
                # Für alte Backends ohne options-Param
                self.write(df, path, sheet_name=name)

    def read_multi(
        self,
        path: str,
        header_levels: int,
        options: BackendOptions | None = None,
    ) -> dict[str, pd.DataFrame]:
        try:
            df = self.read(path, header_levels, sheet_name="Daten", options=options)
        except TypeError:
            df = self.read(path, header_levels, sheet_name="Daten")
        return {"Daten": df}
