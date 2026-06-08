"""Interim resolver for the foundation column-role taxonomy.

Computes role classification for a projected frame by reading scattered
upstream sources:

* `row_identity`: explicit override, else `row_keys` declared on
  `contract_xref` for the same frame name (matrix output),
  else empty.
* `display_helper`: explicit override, else the union of
  `helper_columns` declared on `configure_workbook_view` for the same
  frame and FK-helper `derived` provenance entries under
  `_meta.derived.sheets.<frame>.helper_columns`.
* `matrix_value`: every column on the frame that is not in
  `row_identity` and not in `display_helper`. Narrowed
  rest-by-exclusion per the foundation FTR; only valid on projected
  matrix / view surfaces.

This is an *interim* strategy. When the foundation FTR ships a unified
column-role metadata channel (e.g.
`_meta.derived.sheets.<frame>.column_roles`), this module switches its
source of truth locally without changing its public function signature.

See `FTR-PROJECTED-FRAME-COLUMN-SEMANTICS-P5` for the taxonomy and
`FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5` for the consuming step.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.transformations.fk_helpers import (
    derived_helper_columns_by_sheet,
)

log = logging.getLogger("sheets.column_roles")

ROLE_ROW_IDENTITY = "row_identity"
ROLE_DISPLAY_HELPER = "display_helper"
ROLE_MATRIX_VALUE = "matrix_value"

ROLE_NAMES: frozenset[str] = frozenset(
    {ROLE_ROW_IDENTITY, ROLE_DISPLAY_HELPER, ROLE_MATRIX_VALUE}
)


class UnknownRoleError(ValueError):
    """Raised when an unknown role name is passed to the resolver / step."""


@dataclass(frozen=True)
class ColumnRoles:
    """Role classification for a single frame.

    Each role list is ordered as the columns appear on the input frame.
    Lists never share members; every column on the frame is in exactly
    one of the three lists (a column the resolver could not classify is
    a `matrix_value` by exclusion).
    """

    frame: str
    row_identity: list[str] = field(default_factory=list)
    display_helper: list[str] = field(default_factory=list)
    matrix_value: list[str] = field(default_factory=list)

    def columns_for(self, role: str) -> list[str]:
        if role == ROLE_ROW_IDENTITY:
            return list(self.row_identity)
        if role == ROLE_DISPLAY_HELPER:
            return list(self.display_helper)
        if role == ROLE_MATRIX_VALUE:
            return list(self.matrix_value)
        raise UnknownRoleError(
            f"Unknown role {role!r}; expected one of {sorted(ROLE_NAMES)!r}"
        )


def resolve_column_roles(
    frames: Mapping[str, Any],
    *,
    frame: str,
    helper_columns: Sequence[str] | None = None,
    key_columns: Sequence[str] | None = None,
) -> ColumnRoles:
    """Resolve column roles for `frame` from scattered metadata sources.

    Parameters
    ----------
    frames:
        Pipeline frames mapping (data frames plus optional `_meta`).
    frame:
        Frame name whose columns are classified. Must reference an
        existing `pandas.DataFrame` in `frames`.
    helper_columns:
        Explicit override for the `display_helper` role. When provided,
        the override wins over scattered upstream sources (no union).
    key_columns:
        Explicit override for the `row_identity` role. Same precedence
        as `helper_columns`.

    Notes
    -----
    Missing `row_identity` is warn-only (`logging.WARNING`); no
    exception. Missing `display_helper` is silent (empty set).
    """
    df = _require_data_frame(frames, frame)
    columns = [str(column) for column in df.columns]
    meta = frames.get("_meta") if isinstance(frames, Mapping) else None

    identity = _resolve_row_identity(
        meta=meta,
        frame=frame,
        columns=columns,
        override=key_columns,
    )
    if not identity:
        log.warning(
            "resolve_column_roles: no row_identity resolved for frame %r; "
            "passing through with empty row_identity set",
            frame,
        )

    helpers = _resolve_display_helper(
        frames=frames,
        meta=meta,
        frame=frame,
        columns=columns,
        override=helper_columns,
    )

    identity_set = set(identity)
    helper_set = set(helpers)
    if identity_set & helper_set:
        overlap = sorted(identity_set & helper_set)
        log.warning(
            "resolve_column_roles: columns %r are both row_identity and "
            "display_helper on frame %r; treating them as row_identity",
            overlap,
            frame,
        )
        helpers = [column for column in helpers if column not in identity_set]
        helper_set = set(helpers)

    classified = identity_set | helper_set
    matrix_values = [column for column in columns if column not in classified]

    return ColumnRoles(
        frame=frame,
        row_identity=list(identity),
        display_helper=list(helpers),
        matrix_value=list(matrix_values),
    )


def _require_data_frame(frames: Mapping[str, Any], frame: str) -> pd.DataFrame:
    if not isinstance(frames, Mapping):
        raise TypeError("frames must be a mapping")
    if frame not in frames:
        raise KeyError(f"Frame {frame!r} not present in pipeline state")
    candidate = frames[frame]
    if not isinstance(candidate, pd.DataFrame):
        raise TypeError(f"Frame {frame!r} must be a pandas DataFrame")
    return candidate


def _resolve_row_identity(
    *,
    meta: Any,
    frame: str,
    columns: Sequence[str],
    override: Sequence[str] | None,
) -> list[str]:
    if override is not None:
        candidates = _string_list(override, "key_columns")
    else:
        candidates = _row_keys_from_xref_meta(meta, frame=frame)
    return _ordered_intersection(candidates, columns)


def _resolve_display_helper(
    *,
    frames: Mapping[str, Any],
    meta: Any,
    frame: str,
    columns: Sequence[str],
    override: Sequence[str] | None,
) -> list[str]:
    if override is not None:
        candidates = _string_list(override, "helper_columns")
    else:
        view_helpers = _view_helper_columns(meta, frame=frame)
        fk_helpers = _fk_helper_provenance_columns(frames, frame=frame)
        candidates = _ordered_union(view_helpers, fk_helpers)
    return _ordered_intersection(candidates, columns)


def _row_keys_from_xref_meta(meta: Any, *, frame: str) -> list[str]:
    if not isinstance(meta, Mapping):
        return []
    configs = meta.get("xref_crosstable")
    if not isinstance(configs, Mapping):
        return []
    for config in configs.values():
        if not isinstance(config, Mapping):
            continue
        if config.get("matrix") != frame:
            continue
        row_keys = config.get("row_keys")
        if isinstance(row_keys, list):
            return [str(key) for key in row_keys]
    return []


def _view_helper_columns(meta: Any, *, frame: str) -> list[str]:
    if not isinstance(meta, Mapping):
        return []
    sheet = _sheet_for_frame(meta, frame=frame)
    if sheet is None:
        return []
    sheet_options = meta.get("sheets")
    if not isinstance(sheet_options, Mapping):
        return []
    entry = sheet_options.get(sheet)
    if not isinstance(entry, Mapping):
        return []
    helpers = entry.get("helper_columns")
    if not isinstance(helpers, list):
        return []
    return [str(column) for column in helpers if isinstance(column, str)]


def _sheet_for_frame(meta: Mapping[str, Any], *, frame: str) -> str | None:
    view = meta.get("workbook_view")
    if not isinstance(view, Mapping):
        return None
    sheets = view.get("sheets")
    if not isinstance(sheets, list):
        return None
    for raw in sheets:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("frame") == frame:
            candidate = raw.get("sheet")
            return str(candidate) if isinstance(candidate, str) else None
    return None


def _fk_helper_provenance_columns(frames: Mapping[str, Any], *, frame: str) -> list[str]:
    by_sheet = derived_helper_columns_by_sheet(frames)
    entries = by_sheet.get(frame, [])
    return [str(entry["column"]) for entry in entries if "column" in entry]


def _string_list(values: Iterable[Any], field_name: str) -> list[str]:
    if isinstance(values, str):
        result = [values]
    else:
        result = list(values)
    invalid = [value for value in result if not isinstance(value, str) or not value.strip()]
    if invalid:
        raise ValueError(f"{field_name} must contain non-empty strings: {invalid!r}")
    return [str(value) for value in result]


def _ordered_intersection(
    candidates: Sequence[str], columns: Sequence[str]
) -> list[str]:
    """Return candidates that exist on the frame, in *frame* column order.

    Within-role order follows the input frame; override / source order
    is intentionally not preserved. This implements the foundation FTR's
    "within-role input-order preservation" promise at the resolver
    boundary so consuming steps inherit it for free.
    """
    candidate_set = set(candidates)
    seen: set[str] = set()
    out: list[str] = []
    for column in columns:
        if column in candidate_set and column not in seen:
            seen.add(column)
            out.append(column)
    return out


def _ordered_union(left: Sequence[str], right: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in (*left, *right):
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
