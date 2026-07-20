"""Small shared tabular-domain validation helpers.

Houses the physical-frame column-label safety boundary shared by domain
transformation families (currently ``xref_crosstable`` and ``cell_codec``),
plus the configured-field-declaration uniqueness check they also share.

Scope is intentionally narrow: these are local, explicit validation helpers
for the *physical table boundary*, not a generic table abstraction, a
generic object-equality framework, serialization infrastructure, a new
metadata model, or a broad pandas wrapper.
"""
from __future__ import annotations

from .physical_labels import (
    ensure_unique_field_declaration,
    ensure_unique_physical_column_labels,
    is_scalar_addressable_label,
)

__all__ = [
    "ensure_unique_field_declaration",
    "ensure_unique_physical_column_labels",
    "is_scalar_addressable_label",
]
