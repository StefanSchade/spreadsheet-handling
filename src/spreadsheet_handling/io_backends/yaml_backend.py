from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd
import yaml

Frames = Dict[str, pd.DataFrame]


def _glob_yaml_files(root: Path) -> Iterable[Path]:
    # Akzeptiere *.yml und *.yaml
    yield from root.glob("*.yml")
    yield from root.glob("*.yaml")


def load_yaml_dir(path: str) -> Frames:
    """
    Liest einen Ordner mit YAML-Dateien in Frames:
      - Jede Datei entspricht einem Sheet
      - Inhalt pro Datei: Liste von Objekten (List[Dict[str, Any]])
      - Leere Dateien/Liste -> leeres DataFrame mit 0 Spalten
    """
    in_dir = Path(path)
    frames: Frames = {}

    if not in_dir.exists():
        raise FileNotFoundError(f"YAML input folder not found: {in_dir}")

    for file in _glob_yaml_files(in_dir):
        sheet_name = file.stem
        with file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)  # kann None, list, dict sein
        if data is None:
            df = pd.DataFrame()
        elif isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            # Falls jemand versehentlich ein Mapping statt einer Liste schreibt:
            # wir nehmen die values, wenn das homogen ist – sonst einzeiliges DF
            values = list(data.values())
            if all(isinstance(x, dict) for x in values):
                df = pd.DataFrame(values)  # type: ignore[arg-type]
            else:
                df = pd.DataFrame([data])
        else:
            # Fallback: wir verpacken skalare in eine Spalte "value"
            df = pd.DataFrame([{"value": data}])

        # Einheitlich Strings (wie bei JSON-Backend): fehlende Werte -> ""
        df = df.where(pd.notnull(df), "")
        frames[sheet_name] = df

    return frames


def save_yaml_dir(frames: Frames, path: str) -> None:
    """
    Schreibt Frames als YAML-Dateien (eine Datei pro Sheet):
      - Listen von Records (List[Dict[str, Any]])
      - Leeres DF -> leere Liste
    """
    out_dir = Path(path)
    out_dir.mkdir(parents=True, exist_ok=True)

    for sheet, df in frames.items():
        file = out_dir / f"{sheet}.yml"
        records: List[dict] = (
            df.to_dict(orient="records") if not df.empty else []
        )
        with file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                records,
                f,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            )
