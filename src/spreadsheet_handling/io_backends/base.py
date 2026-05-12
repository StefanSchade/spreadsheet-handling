from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, Mapping, cast

import pandas as pd


@dataclass
class BackendOptions:
    """
    Shared optional I/O policies.
    - levels: requested header levels when reading/writing (if relevant)
    - helper_prefix: helper-column prefix (export policy only)
    - drop_helper_columns: drop helper columns during writes (for example JSON export)
    - extras: backend-specific additions without expanding function signatures
    """

    levels: int | None = None
    helper_prefix: str = "_"
    drop_helpers_on_export: bool | None = None
    encoding: str | None = None
    extra: Dict[str, Any] = field(default_factory=dict)


def coerce_backend_options(
    opts: Mapping[str, Any] | BackendOptions | None,
) -> BackendOptions:
    """
    Accept None | dict | BackendOptions and return a BackendOptions-compatible object.

    If a mapping matches the dataclass fields exactly, construct BackendOptions.
    Otherwise preserve the mapping so backend-specific keys still flow through.
    """
    if opts is None:
        return BackendOptions()
    if isinstance(opts, BackendOptions):
        return opts
    if is_dataclass(BackendOptions):
        dataclass_fields = {field_info.name for field_info in fields(BackendOptions)}
        if set(opts).issubset(dataclass_fields):
            return BackendOptions(**dict(opts))
    return cast(BackendOptions, dict(opts))


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
            self.write(df, path, sheet_name=name, options=options)

    def read_multi(
        self,
        path: str,
        header_levels: int,
        options: BackendOptions | None = None,
    ) -> dict[str, pd.DataFrame]:
        df = self.read(path, header_levels, sheet_name="Daten", options=options)
        return {"Daten": df}
