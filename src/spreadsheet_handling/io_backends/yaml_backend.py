from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd
import yaml

from .base import BackendOptions

Frames = Dict[str, pd.DataFrame]


def _glob_yaml_files(root: Path) -> Iterable[Path]:
    # Accept *.yml and *.yaml.
    yield from root.glob("*.yml")
    yield from root.glob("*.yaml")


def load_yaml_dir(
    path: str,
    options: BackendOptions | None = None,
    *,
    header_levels: int = 1,
) -> Frames:
    """
    Read a folder of YAML files into frames:
      - each file maps to one sheet
      - each file contains a list of objects (List[Dict[str, Any]])
      - empty files/lists become empty DataFrames with 0 columns
    """
    in_dir = Path(path)
    frames: Frames = {}

    if not in_dir.exists():
        raise FileNotFoundError(f"YAML input folder not found: {in_dir}")

    for file in _glob_yaml_files(in_dir):
        sheet_name = file.stem
        with file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)  # may be None, list, or dict
        if data is None:
            df = pd.DataFrame()
        elif isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            # If a file contains a mapping instead of a list, use homogeneous
            # dict values as rows; otherwise wrap the mapping as one row.
            values = list(data.values())
            if all(isinstance(x, dict) for x in values):
                df = pd.DataFrame(values)  # type: ignore[arg-type]
            else:
                df = pd.DataFrame([data])
        else:
            # Fallback: wrap scalars in a "value" column.
            df = pd.DataFrame([{"value": data}])

        # Normalize missing values to "" like the JSON backend.
        df = df.where(pd.notnull(df), "")
        frames[sheet_name] = df

    return frames


def save_yaml_dir(
    frames: Frames,
    path: str,
    options: BackendOptions | None = None,
) -> None:
    """
    Write frames as YAML files, one file per sheet:
      - record lists (List[Dict[str, Any]])
      - empty DataFrames become empty lists
    """
    out_dir = Path(path)
    out_dir.mkdir(parents=True, exist_ok=True)

    for sheet, df in frames.items():
        if sheet == "_meta":
            continue
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
