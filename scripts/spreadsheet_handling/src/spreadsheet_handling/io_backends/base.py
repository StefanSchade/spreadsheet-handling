from __future__ import annotations
from typing import Optional
import pandas as pd

class BackendBase:
    def write(self, df: pd.DataFrame, path: str, sheet_name: str = "Daten") -> None:
        raise NotImplementedError

    def read(self, path: str, header_levels: int, sheet_name: Optional[str] = None) -> pd.DataFrame:
        raise NotImplementedError

    # optionale Multi-Sheet API (die Tests nutzen nur die Klassennamen/Signaturen)
    def write_multi(self, sheets: dict[str, pd.DataFrame], path: str) -> None:
        for name, df in sheets.items():
            self.write(df, path, sheet_name=name)

    def read_multi(self, path: str, header_levels: int) -> dict[str, pd.DataFrame]:
        return {"Daten": self.read(path, header_levels, sheet_name="Daten")}

