"""Frozen, backend-neutral grouped-header model for GX-1.

GX-1 of ``FTR-XREF-AXIS-MAPPINGS-P4A2`` (merged grouped-XRef capability). This
module owns the authoritative, lossless description of a flat canonical-string
matrix's columns:

* :class:`RowKeyColumn` -- a single-level row-key column (physical label);
* :class:`DynamicColumn` -- a dynamic column carrying its exact visible label
  tuple (canonical keys are *not* stored here; they live on the flat DataFrame);
* :class:`GroupedHeader` -- the ordered per-column descriptor plus level names.

The descriptor is a pure value object: exact built-in strings/tuples/ints,
frozen, hashable, value-equal, retaining no caller-owned mutable container and no
DataFrame. It is deliberately decoupled from ``pandas.MultiIndex``, from ``" / "``
flattening, and from merge geometry (see the GX-1 confirmation review).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass

from spreadsheet_handling.domain.tabular import ensure_unique_field_declaration


class GroupedHeaderError(ValueError):
    """A deliberate diagnostic raised by the grouped-header model/primitive."""


def _unsupported_type_detail() -> str:
    """Describe an invalid type without inspecting caller-controlled metadata."""
    return "unsupported value type"


def _require_non_empty_string(value: object, *, field_name: str) -> str:
    if type(value) is not str:
        raise GroupedHeaderError(
            f"{field_name} must be an exact built-in non-empty string; "
            f"got {_unsupported_type_detail()}"
        )
    if not str.strip(value):
        raise GroupedHeaderError(
            f"{field_name} must be an exact built-in non-empty string"
        )
    return value


def _require_position(value: object, *, field_name: str) -> int:
    if type(value) is not int:
        raise GroupedHeaderError(
            f"{field_name} must be an exact built-in integer"
        )
    if value < 0:
        raise GroupedHeaderError(f"{field_name} must not be negative")
    return value


def _owned_string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    """Copy an ordered sequence of exact non-empty strings into an owned tuple."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise GroupedHeaderError(
            f"{field_name} must be an ordered sequence of strings"
        )
    owned = tuple(value)
    for index, item in enumerate(owned):
        _require_non_empty_string(item, field_name=f"{field_name}[{index}]")
    return owned


@dataclass(frozen=True)
class RowKeyColumn:
    """A single-level row-key column identified by its physical label."""

    label: str
    position: int

    def __post_init__(self) -> None:
        _require_non_empty_string(self.label, field_name="RowKeyColumn.label")
        _require_position(self.position, field_name="RowKeyColumn.position")


@dataclass(frozen=True)
class DynamicColumn:
    """A dynamic column carrying its exact visible label tuple and position."""

    labels: tuple[str, ...]
    position: int

    def __post_init__(self) -> None:
        if type(self.labels) is not tuple:
            raise GroupedHeaderError(
                "DynamicColumn.labels must be an exact built-in tuple of "
                "visible labels"
            )
        if not self.labels:
            raise GroupedHeaderError(
                "DynamicColumn.labels must contain at least one visible label"
            )
        for index, label in enumerate(self.labels):
            _require_non_empty_string(
                label, field_name=f"DynamicColumn.labels[{index}]"
            )
        _require_position(self.position, field_name="DynamicColumn.position")


@dataclass(frozen=True)
class GroupedHeader:
    """Immutable, ordered per-column descriptor plus level names.

    ``level_names`` are top-to-leaf and fix the dynamic-label arity. ``columns``
    is in physical column order; each ``position`` equals its index.
    """

    level_names: tuple[str, ...]
    columns: tuple[RowKeyColumn | DynamicColumn, ...]

    def __post_init__(self) -> None:
        level_names = _owned_string_tuple(
            self.level_names, field_name="level_names"
        )
        if not level_names:
            raise GroupedHeaderError("level_names must contain at least one name")
        try:
            ensure_unique_field_declaration(level_names, field_name="level_names")
        except ValueError as exc:
            raise GroupedHeaderError(f"Invalid grouped header: {exc}") from None
        object.__setattr__(self, "level_names", level_names)

        if isinstance(self.columns, (str, bytes, Mapping, Set)):
            raise GroupedHeaderError(
                "columns must be an ordered sequence of grouped-header columns"
            )
        columns = tuple(self.columns)
        arity = len(level_names)
        for expected_position, column in enumerate(columns):
            if type(column) is not RowKeyColumn and type(column) is not DynamicColumn:
                raise GroupedHeaderError(
                    "columns must contain only RowKeyColumn or DynamicColumn values"
                )
            if column.position != expected_position:
                raise GroupedHeaderError(
                    "grouped header column positions must be contiguous and start "
                    f"at zero; expected {expected_position}, got {column.position}"
                )
            if type(column) is DynamicColumn and len(column.labels) != arity:
                raise GroupedHeaderError(
                    f"DynamicColumn at position {column.position} has label tuple "
                    f"arity {len(column.labels)}; expected {arity}"
                )
        object.__setattr__(self, "columns", columns)

    @property
    def arity(self) -> int:
        """Number of visible label levels every dynamic column carries."""
        return len(self.level_names)


__all__ = [
    "GroupedHeaderError",
    "RowKeyColumn",
    "DynamicColumn",
    "GroupedHeader",
]
