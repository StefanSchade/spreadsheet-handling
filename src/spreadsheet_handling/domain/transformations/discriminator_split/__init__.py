"""Split and merge frames by a discriminator column.

Split into a package (FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-DISCRIMINATOR-P5)
from the former single ``discriminator_split`` module, with no behavior,
step-name, YAML, ordering, metadata-payload, or split/merge-symmetry change.

The internal file layout is an implementation detail. Callers (the pipeline
registry colon-target, ``meta_registry.yaml`` producer/consumer dotted paths,
and tests) use only the two names re-exported here:
``domain.transformations.discriminator_split.split_by_discriminator`` and
``...merge_by_discriminator``.
"""

from __future__ import annotations

from .merge import merge_by_discriminator
from .split import split_by_discriminator

__all__ = [
    "split_by_discriminator",
    "merge_by_discriminator",
]
