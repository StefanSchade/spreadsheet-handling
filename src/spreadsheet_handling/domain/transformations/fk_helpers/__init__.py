"""FK-helper domain transformations: enrichment and cleanup.

Extracted from pipeline.steps (FTR-FK-HELPER-DOMAIN-EXTRACTION) and split into
a package (FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-FK-HELPERS-P5). Pipeline step
factories delegate here; this package owns the full FK-helper lifecycle:
resolution, enrichment, provenance, and cleanup.

The internal file layout is an implementation detail. Callers (pipeline
registry, tests, documented producer/consumer symbol paths) use the names
re-exported here, e.g. ``domain.transformations.fk_helpers.enrich_helpers``.

``FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5`` made the primitives consume
the v2 FK relation policy and the derived helper provenance. The policy and
provenance readers are re-exported here so v2-aware consumers outside the
package (the ``reorder_fk_helpers`` step, FK-helper validation) can read
the contract without importing internal sibling modules.
"""
from __future__ import annotations

from .drop import drop_helpers
from .enrich import enrich_helpers
from .policy import (
    MissingFkRelationPolicyError,
    derived_helper_columns_by_sheet,
    missing_fk_policy_error,
    resolve_v2_fk_relations,
)
from .provenance import _write_helper_provenance

__all__ = [
    "enrich_helpers",
    "drop_helpers",
    "_write_helper_provenance",
    "MissingFkRelationPolicyError",
    "derived_helper_columns_by_sheet",
    "missing_fk_policy_error",
    "resolve_v2_fk_relations",
]
