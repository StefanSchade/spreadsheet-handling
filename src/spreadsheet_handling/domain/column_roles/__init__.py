"""Shared column-role resolution.

Public surface for the foundation column-role taxonomy
(`FTR-PROJECTED-FRAME-COLUMN-SEMANTICS-P5`):
`row_identity`, `display_helper`, `matrix_value`.

The resolver is the single source of truth for role detection in the
current code base. Both `project_by_role`
(`FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5`) and the future targeting
implementation slice (`FTR-DYNAMIC-VIEW-COLUMN-TARGETING-IMPL-P5`)
must consume it; neither may implement parallel role detection.
"""

from .resolver import (
    ROLE_DISPLAY_HELPER,
    ROLE_MATRIX_VALUE,
    ROLE_ROW_IDENTITY,
    ROLE_NAMES,
    ColumnRoles,
    UnknownRoleError,
    resolve_column_roles,
)

__all__ = [
    "ROLE_DISPLAY_HELPER",
    "ROLE_MATRIX_VALUE",
    "ROLE_ROW_IDENTITY",
    "ROLE_NAMES",
    "ColumnRoles",
    "UnknownRoleError",
    "resolve_column_roles",
]
