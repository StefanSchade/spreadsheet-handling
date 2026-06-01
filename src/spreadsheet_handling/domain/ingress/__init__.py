"""Internal domain ingress boundary.

Normalizes externally authored ``_meta`` into canonical domain shape at every
maintained external-to-domain entry point. Framework-owned macro flow, not a
public/YAML-addressable pipeline step. See :mod:`.coordinator`.
"""

from __future__ import annotations

from .coordinator import INGRESS_RULES, IngressRule, run_domain_ingress
from .legend_blocks import normalize_legend_blocks_shape

__all__ = [
    "INGRESS_RULES",
    "IngressRule",
    "run_domain_ingress",
    "normalize_legend_blocks_shape",
]
