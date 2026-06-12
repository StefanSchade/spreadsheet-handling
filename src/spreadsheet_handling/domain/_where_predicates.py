"""Shared private where-predicate engine for domain filter steps.

Houses the bounded ``where:`` filter shared by ``join_views.join_frames`` and
``extractions.extract_frame``. Centralising removes silent-drift risk; the
implementations were verbatim duplicates and are relocated unchanged.

Out of scope (intentionally not extracted): the
``validations.reference_validations`` predicate path (``_condition_mask`` /
``_apply_when``) - those add ``_format_scalar``/``_plain_value``
normalisation, ``optional_missing``, and ``enabled_when`` switch-frame
integration, and are not equivalent to this engine.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain._cell_primitives import _is_empty_cell

_WHERE_PREDICATES = {"equals", "in", "non_empty", "is_null", "not_null"}


def _ensure_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    *,
    frame_name: str,
    field_name: str,
) -> None:
    requested = list(columns)
    missing = [column for column in requested if column not in frame.columns]
    if missing:
        raise KeyError(
            f"Frame {frame_name!r} is missing configured {field_name} column(s): {missing!r}"
        )


def _duplicate_column_names(frame: pd.DataFrame) -> list[Any]:
    columns = list(frame.columns)
    return list(dict.fromkeys(column for column in columns if columns.count(column) > 1))


def _ensure_boolean_predicate(value: Any, predicate: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"where.{predicate} must be true or false")


def _apply_where(
    source: pd.DataFrame,
    where: Mapping[str, Any] | None,
    *,
    frame_name: str,
) -> pd.DataFrame:
    if where is None:
        return source.copy()
    if not isinstance(where, Mapping):
        raise TypeError("where must be a mapping with `column` plus one supported predicate")

    column = where.get("column")
    if not isinstance(column, str) or not column.strip():
        raise ValueError("where.column must be a non-empty string")
    _ensure_columns(source, [column], frame_name=frame_name, field_name="where")

    predicates = [key for key in where if key in _WHERE_PREDICATES]
    unsupported = [key for key in where if key not in {*_WHERE_PREDICATES, "column"}]
    if unsupported:
        raise ValueError(
            f"Unsupported where predicate(s) {unsupported!r}; "
            f"supported predicates are {sorted(_WHERE_PREDICATES)!r}"
        )
    if len(predicates) != 1:
        raise ValueError(
            "where must configure exactly one predicate among " f"{sorted(_WHERE_PREDICATES)!r}"
        )

    predicate = predicates[0]
    values = source[column]
    if predicate == "equals":
        mask = values == where[predicate]
    elif predicate == "in":
        members = where[predicate]
        if isinstance(members, (str, bytes)) or not isinstance(members, Iterable):
            raise TypeError("where.in must be a list of allowed values, not a scalar")
        mask = values.isin(list(members))
    elif predicate == "non_empty":
        _ensure_boolean_predicate(where[predicate], predicate)
        mask = values.map(lambda value: not _is_empty_cell(value))
        if where[predicate] is False:
            mask = ~mask
    elif predicate == "is_null":
        _ensure_boolean_predicate(where[predicate], predicate)
        mask = values.isnull()
        if where[predicate] is False:
            mask = ~mask
    elif predicate == "not_null":
        _ensure_boolean_predicate(where[predicate], predicate)
        mask = values.notnull()
        if where[predicate] is False:
            mask = ~mask
    else:  # pragma: no cover - guarded above
        raise AssertionError(predicate)
    return source.loc[mask].copy()
