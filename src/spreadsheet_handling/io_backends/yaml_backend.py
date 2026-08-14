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


# Trusted Ingress YAML Option A (`FTR-TRUSTED-INGRESS-P4A` section 11, accepted
# unchanged by the E3 metadata census): the stem ``_meta`` is reserved for a
# framework metadata sidecar, never an ordinary DataFrame sheet. At most one of
# ``_meta.yaml``/``_meta.yml`` may be present; its root must be a mapping. Both
# are backend/parse-boundary facts owned here -- Domain ingress (Phase-E E3)
# never reinterprets an ordinary DataFrame as metadata, and never sees a
# DataFrame at this key at all now.
_RESERVED_META_STEM = "_meta"


def _load_reserved_meta_sidecar(reserved_files: list[Path]) -> dict[str, Any] | None:
    if not reserved_files:
        return None
    if len(reserved_files) > 1:
        names = ", ".join(repr(f.name) for f in sorted(reserved_files, key=lambda f: f.name))
        raise ValueError(
            "YAML directory reserved metadata sidecar is ambiguous: found "
            f"{names}; provide at most one of '_meta.yaml' or '_meta.yml'."
        )
    sidecar = reserved_files[0]
    with sidecar.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if type(loaded) is not dict:
        actual = "an empty file (None)" if loaded is None else type(loaded).__name__
        raise ValueError(
            f"YAML directory reserved metadata sidecar {sidecar.name!r} must "
            f"be a mapping at its root; got {actual}."
        )
    return loaded


def _ordinary_sheet_dataframe(data: Any) -> pd.DataFrame:
    """Convert one ordinary (non-reserved) YAML file's parsed content to a sheet."""
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
    return df.where(pd.notnull(df), "")


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
      - a file whose stem is ``_meta`` is a reserved metadata sidecar, not an
        ordinary sheet (Trusted Ingress YAML Option A; see
        ``_load_reserved_meta_sidecar``)
    """
    in_dir = Path(path)
    frames: Frames = {}

    if not in_dir.exists():
        raise FileNotFoundError(f"YAML input folder not found: {in_dir}")

    all_files = list(_glob_yaml_files(in_dir))
    reserved_files = [f for f in all_files if f.stem == _RESERVED_META_STEM]
    ordinary_files = [f for f in all_files if f.stem != _RESERVED_META_STEM]

    meta = _load_reserved_meta_sidecar(reserved_files)
    if meta is not None:
        frames["_meta"] = meta  # type: ignore[assignment]

    for file in ordinary_files:
        with file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)  # may be None, list, or dict
        frames[file.stem] = _ordinary_sheet_dataframe(data)

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
