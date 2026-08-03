"""Shared column-role resolution.

Public surface for the foundation column-role taxonomy
(`FTR-PROJECTED-FRAME-COLUMN-SEMANTICS-P5`):
`row_identity`, `display_helper`, `matrix_value`.

The resolver is the shared source of truth for role-aware targeting and
other current consumers in the code base. Role-targeted validation
(`validate_columns`, `FTR-DYNAMIC-VIEW-COLUMN-TARGETING-IMPL-P5`)
consumes it and must not implement parallel role detection. The former
`project_by_role` projection step also consumed it before it was retired
by `FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2`.
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
