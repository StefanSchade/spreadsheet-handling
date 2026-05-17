"""FK-helper domain transformations: enrichment and cleanup.

Extracted from pipeline.steps (FTR-FK-HELPER-DOMAIN-EXTRACTION) and split into
a package (FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-FK-HELPERS-P5). Pipeline step
factories delegate here; this package owns the full FK-helper lifecycle:
resolution, enrichment, provenance, and cleanup.

The internal file layout is an implementation detail. Callers (pipeline
registry, tests, documented producer/consumer symbol paths) use the names
re-exported here, e.g. ``domain.transformations.fk_helpers.enrich_helpers``.
"""
from __future__ import annotations

from .drop import drop_helpers
from .enrich import enrich_helpers
from .provenance import _write_helper_provenance

__all__ = [
    "enrich_helpers",
    "drop_helpers",
    "_write_helper_provenance",
]
