from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
import yaml

from .base import BackendOptions

Frames = Dict[str, pd.DataFrame]


def _yaml_safe_temporal(value: Any) -> Any:
    """Persistence-local temporal carrier conversion for `save_yaml_dir`.

    Ordered checks -- `pandas.NaT` before `pandas.Timestamp` before
    everything else -- per the accepted D-T2.1 contract
    (`FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` section 27.6):

    * `value is pd.NaT` (temporal Missing) -> `None`, matching a
      `datetime.date` column's own already-working `None` -> YAML `null`
      Missing representation.
    * `isinstance(value, pd.Timestamp)` -> `value.as_unit("us").to_pydatetime()`,
      so PyYAML's native timestamp scalar receives a plain
      `datetime.datetime` at microsecond precision, with no `UserWarning`
      side effect (unlike bare `.to_pydatetime()` on a nanosecond-precision
      `Timestamp`).
    * everything else (`datetime.date`, plain `datetime.datetime`, `str`,
      `int`, `float`, `bool`, `None`) is returned unchanged -- YAML's native
      `date`/`timestamp` tags already round-trip those correctly.

    Private, unexported, and scoped to exactly `save_yaml_dir`'s own record
    mapping -- not a general normalization primitive
    (`normalize_scalar()`-shaped or otherwise), not part of Trusted Ingress,
    and not imported by `json_backend.py`, any Domain module, or
    `core/scalar_values.py`. No global `yaml.SafeDumper` representer is
    registered; this is a value-level conversion applied before
    `yaml.safe_dump` sees the record, not a representer.
    """
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.as_unit("us").to_pydatetime()
    return value


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
      - header_levels is accepted for router compatibility; YAML has no header rows
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
        records = [
            {key: _yaml_safe_temporal(value) for key, value in record.items()}
            for record in records
        ]
        with file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                records,
                f,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            )
