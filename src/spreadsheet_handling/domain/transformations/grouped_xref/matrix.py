"""Feature-owned Frames-boundary carrier for the grouped-XRef composites (GX-2).

GX-2 of ``FTR-XREF-AXIS-MAPPINGS-P4A2`` (merged grouped-XRef capability). A
:class:`GroupedMatrix` bundles the flat canonical-string matrix DataFrame and its
:class:`GroupedHeader` descriptor as a *single* Frames value, so the two travel
together as a trusted pair (see the GX-2 confirmation review, "Pairing
solution"). This makes the GX1-A-M2 mispairing hazard structurally unreachable
through the public composite surface: ``contract_grouped_xref`` is the only
producer, ``expand_grouped_xref`` the only consumer, and the inverse exposes no
descriptor parameter.

The carrier is deliberately *not* a value object. It holds a mutable pandas
DataFrame, exactly as a Frames mapping already holds mutable DataFrames as its
values, so it uses identity semantics (``eq=False``) and does not claim
value-equality. It never copies the frame to feign immutability, stores nothing
in ``_meta``, builds no ``MultiIndex``, and persists no mapping.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .model import GroupedHeader


class GroupedXrefError(ValueError):
    """A deliberate diagnostic raised by the grouped-XRef composites (GX-2).

    Used only for composite-owned structural and public-input failures. Domain
    failures keep their own error types: resolver failures stay
    ``AxisMappingError``, grouped-header failures stay ``GroupedHeaderError``,
    and XRef failures stay XRef ``ValueError`` s.
    """


@dataclass(frozen=True, eq=False)
class GroupedMatrix:
    """Opaque carrier of a flat canonical matrix plus its grouped descriptor.

    ``frame`` is the flat, canonical-string-headed matrix produced by unchanged
    ``contract_xref``; ``header`` is the immutable GX-1 :class:`GroupedHeader`
    that describes its dynamic columns' visible label tuples. The two are a
    trusted pair built together by ``contract_grouped_xref``.

    Identity semantics: two carriers with equal content are *not* equal; the
    carrier is not a hashable *value* object. ``frozen=True`` only prevents
    rebinding the two references; it makes no false immutability claim about the
    contained DataFrame.
    """

    frame: pd.DataFrame
    header: GroupedHeader

    def __post_init__(self) -> None:
        if not isinstance(self.frame, pd.DataFrame):
            raise GroupedXrefError(
                "GroupedMatrix.frame must be a pandas DataFrame"
            )
        if type(self.header) is not GroupedHeader:
            raise GroupedXrefError(
                "GroupedMatrix.header must be a GroupedHeader descriptor"
            )


__all__ = [
    "GroupedMatrix",
    "GroupedXrefError",
]
