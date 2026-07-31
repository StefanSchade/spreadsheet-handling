"""Feature-local grouped-header model and pure projection primitives.

GX-1 of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. This package exports only typed domain
values and the two pure primitives for feature-internal consumption (GX-2). It
is not a pipeline or public YAML surface: no step, no registry entry, no
``_meta``, no carrier.
"""
from __future__ import annotations

from .model import (
    DynamicColumn,
    GroupedHeader,
    GroupedHeaderError,
    RowKeyColumn,
)
from .projection import build_grouped_header, restore_flat_matrix

__all__ = [
    "GroupedHeaderError",
    "RowKeyColumn",
    "DynamicColumn",
    "GroupedHeader",
    "build_grouped_header",
    "restore_flat_matrix",
]
