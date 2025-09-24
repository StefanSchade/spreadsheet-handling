from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from .base import BackendBase, BackendOptions


class JSONBackend(BackendBase):
    """Liest/schreibt einen Ordner mit {sheet}.json-Dateien (Liste von Objekten je Datei)."""

    def write_multi(
        self,
        sheets: dict[str, pd.DataFrame],
        path: str,
        options: BackendOptions | None = None,
    ) -> None:
        out_dir = Path(path)
        out_dir.mkdir(parents=True, exist_ok=True)

        helper_prefix = options.helper_prefix if options else "_"
        drop_helpers = (
            options.drop_helpers_on_export
            if (options and options.drop_helpers_on_export is not None)
            else True  # JSON: per default Helper nicht mit exportieren
        )
        encoding = options.encoding if (options and options.encoding) else "utf-8"

        for name, df in sheets.items():
            df_out = df.copy()

            # Level-0-Header flatten
            if isinstance(df_out.columns, pd.MultiIndex):
                lvl0 = [t[0] for t in df_out.columns.to_list()]
                df_out.columns = lvl0

            # Helper-Spalten optional entfernen
            if drop_helpers and helper_prefix:
                keep = [
                    c
                    for c in df_out.columns
                    if not (isinstance(c, str) and c.startswith(helper_prefix))
                ]
                df_out = df_out[keep]

            # NaN -> None, dann JSON schreiben
            records = df_out.where(pd.notnull(df_out), None).to_dict(orient="records")
            with (out_dir / f"{name}.json").open("w", encoding=encoding) as f:
                json.dump(records, f, ensure_ascii=False, indent=2)

    def read_multi(
        self,
        path: str,
        header_levels: int,
        options: BackendOptions | None = None,
    ) -> dict[str, pd.DataFrame]:
        in_dir = Path(path)
        if not in_dir.is_dir():
            raise FileNotFoundError(f"{in_dir} ist kein Verzeichnis")

        levels = (
            int(options.levels) if (options and options.levels is not None) else int(header_levels)
        )
        encoding = options.encoding if (options and options.encoding) else "utf-8"

        out: dict[str, pd.DataFrame] = {}
        for p in sorted(in_dir.glob("*.json")):
            with p.open("r", encoding=encoding) as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                raise ValueError(f"Ungültige JSON-Struktur in {p}: erwartet Liste/Objekt")

            df = pd.DataFrame(data)
            # Spalten in MultiIndex heben (nur Level-0 belegt, Rest leer)
            tuples = [(c,) + ("",) * (levels - 1) for c in list(df.columns)]
            df.columns = pd.MultiIndex.from_tuples(tuples)
            out[p.stem] = df

        if not out:
            raise FileNotFoundError(f"Keine *.json in {in_dir} gefunden.")
        return out
