from __future__ import annotations
import pandas as pd
from .base import BackendBase

class ODSBackend(BackendBase):
    """
    Platzhalter. Idee:
    - Schreiben: odfpy nutzen, Multi-Level-Header als mehrere Zeilen.
    - Lesen: ODS → DataFrame (ggf. tablib/pyexcel als Zwischenweg).
    """
    def write(self, df: pd.DataFrame, path: str, sheet_name: str = "Daten") -> None:
        raise NotImplementedError("ODS write not implemented yet. Planned via 'odfpy'.")

    def read(self, path: str, header_levels: int, sheet_name: str = "Daten") -> pd.DataFrame:
        raise NotImplementedError("ODS read not implemented yet. Planned via 'odfpy'.")

