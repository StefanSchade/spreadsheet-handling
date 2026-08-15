"""Internal domain ingress boundary.

Normalizes externally authored ``_meta`` into canonical domain shape at every
maintained external-to-domain entry point. Framework-owned macro flow, not a
public/YAML-addressable pipeline step. See :mod:`.coordinator`.

Not part of the supported public Python import surface (Trusted Ingress
slice E6): everything in this package, including ``run_domain_ingress``, is
internal/importable-only -- no explicit conformance-establishment helper is
publicly promised here. Supported programmatic callers reach this
machinery only indirectly, through ``application.orchestrator.orchestrate``
(or ``run_app``/``sheets-run``/``sheets-schema-maintain``). See
``docs/ai_info/interfaces_and_gates.adoc`` and ``docs/backlog/
FTR-TRUSTED-INGRESS-P4A.adoc`` section 46 for the decision and its evidence.
"""

from __future__ import annotations

from .coordinator import INGRESS_RULES, IngressRule, run_domain_ingress
from .legend_blocks import normalize_legend_blocks_shape
from .metadata_admission import (
    MetadataSubstrateAdmissionError,
    admit_metadata_substrate,
)

__all__ = [
    "INGRESS_RULES",
    "IngressRule",
    "run_domain_ingress",
    "normalize_legend_blocks_shape",
    "MetadataSubstrateAdmissionError",
    "admit_metadata_substrate",
]
