"""Internal pure model and resolver for XRef axis mappings.

Slice 1 intentionally exports only typed domain values and the resolver from
this feature-local package. It is not a pipeline or public YAML surface.
"""
from __future__ import annotations

from .model import (
    AxisMappingError,
    AxisMappingIntent,
    AxisOrderPolicy,
    ResolvedAxisMapping,
    ResolvedAxisMember,
)
from .resolver import resolve_axis_mapping

__all__ = [
    "AxisMappingError",
    "AxisMappingIntent",
    "AxisOrderPolicy",
    "ResolvedAxisMapping",
    "ResolvedAxisMember",
    "resolve_axis_mapping",
]
