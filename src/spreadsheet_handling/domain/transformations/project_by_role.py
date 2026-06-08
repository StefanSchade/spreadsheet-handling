"""Role-based column projection for projected matrix / view surfaces.

Implements `FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5`. Backend-neutral
in-place transform that reorders / retains the columns of `frame`
according to the foundation column-role taxonomy. The step delegates
role detection to
`spreadsheet_handling.domain.column_roles.resolver.resolve_column_roles`
and must never implement its own.

The step is in-place: it mutates the named frame's column sequence
and produces no new output frame. There is no `source:` / `output:`
parameter; pipeline authors must produce the intended frame name
before invoking the step.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.column_roles import (
    ROLE_DISPLAY_HELPER,
    ROLE_MATRIX_VALUE,
    ROLE_NAMES,
    ROLE_ROW_IDENTITY,
    ColumnRoles,
    resolve_column_roles,
)

Frames = dict[str, Any]

_VALID_DIRECTIONS = ("outbound", "inbound")
_DEFAULT_OUTBOUND_ORDER = (ROLE_DISPLAY_HELPER, ROLE_ROW_IDENTITY, ROLE_MATRIX_VALUE)
_DEFAULT_INBOUND_ORDER = (ROLE_ROW_IDENTITY, ROLE_MATRIX_VALUE)
_OUTBOUND_REQUIRED_ROLES = frozenset(_DEFAULT_OUTBOUND_ORDER)
_INBOUND_ALLOWED_ROLES = frozenset(_DEFAULT_INBOUND_ORDER)


def project_by_role(
    frames: Mapping[str, Any],
    *,
    frame: str,
    direction: str,
    helper_columns: Sequence[str] | None = None,
    key_columns: Sequence[str] | None = None,
    role_order: Sequence[str] | None = None,
    name: str | None = None,
) -> Frames:
    """Apply role-based projection to `frame` in place.

    See `FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5` for the parameter
    contract and outbound/inbound semantics.
    """
    del name
    if not isinstance(frame, str) or not frame.strip():
        raise ValueError("frame must be a non-empty string")
    direction_value = _validate_direction(direction)
    order = _validate_role_order(role_order, direction=direction_value)

    roles = resolve_column_roles(
        frames,
        frame=frame,
        helper_columns=helper_columns,
        key_columns=key_columns,
    )

    if direction_value == "outbound":
        new_columns = _outbound_columns(roles, order)
    else:
        new_columns = _inbound_columns(roles, order)

    out: Frames = dict(frames)
    out[frame] = _reorder_dataframe(out[frame], new_columns)
    return out


def _validate_direction(direction: Any) -> str:
    if direction is None:
        raise ValueError(
            "project_by_role requires explicit 'direction'; "
            f"accepted values: {list(_VALID_DIRECTIONS)!r}"
        )
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(
            f"project_by_role direction must be one of {list(_VALID_DIRECTIONS)!r}, "
            f"got {direction!r}"
        )
    return str(direction)


def _validate_role_order(
    role_order: Sequence[str] | None,
    *,
    direction: str,
) -> tuple[str, ...]:
    if role_order is None:
        return (
            _DEFAULT_OUTBOUND_ORDER if direction == "outbound" else _DEFAULT_INBOUND_ORDER
        )
    order = tuple(role_order)
    unknown = [role for role in order if role not in ROLE_NAMES]
    if unknown:
        raise ValueError(
            f"project_by_role role_order contains unknown role(s) {unknown!r}; "
            f"expected names from {sorted(ROLE_NAMES)!r}"
        )
    if len(set(order)) != len(order):
        raise ValueError(
            f"project_by_role role_order must not repeat role names: {list(order)!r}"
        )
    if direction == "outbound":
        if set(order) != _OUTBOUND_REQUIRED_ROLES:
            raise ValueError(
                "project_by_role direction='outbound' requires role_order to be "
                "a permutation of "
                f"{sorted(_OUTBOUND_REQUIRED_ROLES)!r}; got {list(order)!r}"
            )
    else:  # inbound
        if ROLE_DISPLAY_HELPER in order:
            raise ValueError(
                "project_by_role direction='inbound' rejects 'display_helper' in "
                f"role_order (inbound drops display_helper); got {list(order)!r}"
            )
        if set(order) != _INBOUND_ALLOWED_ROLES:
            raise ValueError(
                "project_by_role direction='inbound' requires role_order to be "
                "a permutation of "
                f"{sorted(_INBOUND_ALLOWED_ROLES)!r}; got {list(order)!r}"
            )
    return order


def _outbound_columns(roles: ColumnRoles, order: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for role in order:
        for column in roles.columns_for(role):
            if column in seen:
                continue
            seen.add(column)
            out.append(column)
    return out


def _inbound_columns(roles: ColumnRoles, order: Sequence[str]) -> list[str]:
    drop = set(roles.display_helper)
    out: list[str] = []
    seen: set[str] = set()
    for role in order:
        for column in roles.columns_for(role):
            if column in drop or column in seen:
                continue
            seen.add(column)
            out.append(column)
    return out


def _reorder_dataframe(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    ordered = [str(column) for column in columns]
    return df.loc[:, ordered].copy()
