"""Ordinary scalar admission for the Trusted Ingress boundary.

This module owns only Phase-E slice E1: validate one candidate ordinary cell
against the accepted six-category Scalar grammar.  Structural traversal,
location context, metadata, controlled framework roles, and orchestration
wiring belong to later Phase-E slices.
"""

from __future__ import annotations

from typing import Literal, TypeVar

from spreadsheet_handling.core.scalar_values import (
    UnsupportedScalarError,
    scalar_category,
)

_ValueT = TypeVar("_ValueT")


class OrdinaryScalarAdmissionError(TypeError):
    """An unsupported carrier was rejected at ordinary scalar admission.

    The exception deliberately stores only safely established type
    information.  It never retains or formats the rejected value, leaving
    later traversal slices free to add safe positional context.
    """

    kind: Literal["unsupported_scalar_carrier"] = "unsupported_scalar_carrier"

    def __init__(self, *, carrier_type_name: str) -> None:
        self.carrier_type_name = carrier_type_name
        super().__init__(
            "unsupported ordinary scalar carrier of type "
            f"'{carrier_type_name}'; expected String, Boolean, Number, Missing, "
            "Date, or DateTime"
        )


def admit_ordinary_scalar(value: _ValueT) -> _ValueT:
    """Validate and return one ordinary Scalar carrier unchanged.

    Recognition is delegated completely to Phase D's ``scalar_category``;
    this boundary does not duplicate classification or normalize accepted
    carriers.  An unsupported value raises ``OrdinaryScalarAdmissionError``
    with a stable kind and a type-only diagnostic.
    """

    try:
        scalar_category(value)
    except UnsupportedScalarError as error:
        raise OrdinaryScalarAdmissionError(
            carrier_type_name=error.value_type_name
        ) from None
    return value


__all__ = [
    "OrdinaryScalarAdmissionError",
    "admit_ordinary_scalar",
]
