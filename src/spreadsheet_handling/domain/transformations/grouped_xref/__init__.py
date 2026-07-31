"""Grouped-XRef feature package.

``FTR-XREF-AXIS-MAPPINGS-P4A2`` (merged grouped-XRef capability).

* GX-1 exports the frozen grouped-header model and the two pure projection
  primitives (``build_grouped_header`` / ``restore_flat_matrix``).
* GX-2 adds the public composites (``contract_grouped_xref`` /
  ``expand_grouped_xref``), the Frames-boundary :class:`GroupedMatrix` carrier,
  and :class:`GroupedXrefError`.

The composites are the public pipeline surface (registered in
``pipeline/registry.py`` and ``registries/pipeline_step_registry.json``); the
GX-1 primitives and the model remain feature-internal. This package is *not*
re-exported from ``domain/transformations/__init__.py``.
"""
from __future__ import annotations

from .model import (
    DynamicColumn,
    GroupedHeader,
    GroupedHeaderError,
    RowKeyColumn,
)
from .projection import build_grouped_header, restore_flat_matrix
from .matrix import GroupedMatrix, GroupedXrefError
from .composites import contract_grouped_xref, expand_grouped_xref

__all__ = [
    "GroupedHeaderError",
    "RowKeyColumn",
    "DynamicColumn",
    "GroupedHeader",
    "build_grouped_header",
    "restore_flat_matrix",
    "GroupedMatrix",
    "GroupedXrefError",
    "contract_grouped_xref",
    "expand_grouped_xref",
]
