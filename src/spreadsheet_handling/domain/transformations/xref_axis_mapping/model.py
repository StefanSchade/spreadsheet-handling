"""Typed values for the internal XRef axis-mapping model."""
from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence, Set
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from spreadsheet_handling.domain.tabular import ensure_unique_field_declaration


class AxisMappingError(ValueError):
    """A deliberate diagnostic raised by the axis-mapping capability."""


class AxisOrderPolicy(str, Enum):
    """Explicit policies supported by the Slice 1 resolver."""

    SOURCE_ROW = "source_row"
    COLUMNS = "columns"


def _unsupported_type_detail() -> str:
    """Describe an invalid type without inspecting caller-controlled type metadata."""
    return "unsupported value type"


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    if type(value) is not str:
        raise AxisMappingError(
            f"{field_name} must be an exact built-in non-empty string; "
            f"got {_unsupported_type_detail()}"
        )
    if not str.strip(value):
        raise AxisMappingError(
            f"{field_name} must be an exact built-in non-empty string"
        )
    return value


def _configured_columns(value: Any, *, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AxisMappingError(
            f"{field_name} must be an ordered sequence of column names"
        )
    columns = tuple(value)
    for index, column in enumerate(columns):
        _require_non_empty_string(column, field_name=f"{field_name}[{index}]")
    try:
        ensure_unique_field_declaration(columns, field_name=field_name)
    except ValueError as exc:
        raise AxisMappingError(f"Invalid axis-mapping intent: {exc}") from None
    return columns


@dataclass(frozen=True)
class AxisMappingIntent:
    """Declarative source, fields, and deliberately selected order policy."""

    source_frame: str
    key_column: str
    label_columns: tuple[str, ...]
    order_policy: AxisOrderPolicy
    order_columns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty_string(self.source_frame, field_name="source_frame")
        _require_non_empty_string(self.key_column, field_name="key_column")
        label_columns = _configured_columns(
            self.label_columns,
            field_name="label_columns",
        )
        if not label_columns:
            raise AxisMappingError("label_columns must contain at least one column")
        object.__setattr__(self, "label_columns", label_columns)

        if type(self.order_policy) is not AxisOrderPolicy:
            raise AxisMappingError(
                "order_policy must be an AxisOrderPolicy; select "
                "AxisOrderPolicy.SOURCE_ROW or AxisOrderPolicy.COLUMNS explicitly"
            )
        order_columns = _configured_columns(
            self.order_columns,
            field_name="order_columns",
        )
        object.__setattr__(self, "order_columns", order_columns)
        if self.order_policy is AxisOrderPolicy.SOURCE_ROW and order_columns:
            raise AxisMappingError(
                "order_columns must be empty when order_policy is SOURCE_ROW"
            )
        if self.order_policy is AxisOrderPolicy.COLUMNS and not order_columns:
            raise AxisMappingError(
                "order_columns must contain at least one column when "
                "order_policy is COLUMNS"
            )


def _resolved_labels(value: Any, *, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise AxisMappingError(
            f"{field_name} must be an exact built-in tuple of visible labels"
        )
    if not value:
        raise AxisMappingError(f"{field_name} must contain at least one visible label")
    for index, label in enumerate(value):
        _require_non_empty_string(label, field_name=f"{field_name}[{index}]")
    return value


@dataclass(frozen=True)
class ResolvedAxisMember:
    """One canonical key, its complete visible label tuple, and position."""

    key: str
    labels: tuple[str, ...]
    position: int

    def __post_init__(self) -> None:
        _require_non_empty_string(self.key, field_name="ResolvedAxisMember.key")
        _resolved_labels(self.labels, field_name="ResolvedAxisMember.labels")
        if type(self.position) is not int:
            raise AxisMappingError(
                "ResolvedAxisMember.position must be an exact built-in integer"
            )
        if self.position < 0:
            raise AxisMappingError("ResolvedAxisMember.position must not be negative")


@dataclass(frozen=True)
class ResolvedAxisMapping:
    """Immutable ordered bijection with exact forward and inverse lookup."""

    label_columns: tuple[str, ...]
    members: tuple[ResolvedAxisMember, ...]
    _labels_by_key: Mapping[str, tuple[str, ...]] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _key_by_labels: Mapping[tuple[str, ...], str] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        label_columns = _configured_columns(
            self.label_columns,
            field_name="ResolvedAxisMapping.label_columns",
        )
        if not label_columns:
            raise AxisMappingError(
                "ResolvedAxisMapping.label_columns must contain at least one column"
            )
        object.__setattr__(self, "label_columns", label_columns)

        if isinstance(self.members, (str, bytes, Mapping, Set)):
            raise AxisMappingError(
                "ResolvedAxisMapping.members must be an ordered iterable of members"
            )
        try:
            members = tuple(self.members)
        except TypeError:
            raise AxisMappingError(
                "ResolvedAxisMapping.members must be an ordered iterable of members"
            ) from None
        object.__setattr__(self, "members", members)

        labels_by_key: dict[str, tuple[str, ...]] = {}
        key_by_labels: dict[tuple[str, ...], str] = {}
        expected_arity = len(label_columns)
        for expected_position, member in enumerate(members):
            if type(member) is not ResolvedAxisMember:
                raise AxisMappingError(
                    "ResolvedAxisMapping.members must contain ResolvedAxisMember values"
                )
            _resolved_labels(
                member.labels,
                field_name=f"ResolvedAxisMapping.members[{expected_position}].labels",
            )
            if member.position != expected_position:
                raise AxisMappingError(
                    "ResolvedAxisMapping member positions must be contiguous and "
                    f"start at zero; expected {expected_position}, got {member.position}"
                )
            if len(member.labels) != expected_arity:
                raise AxisMappingError(
                    f"ResolvedAxisMapping member {member.key!r} has label tuple "
                    f"arity {len(member.labels)}; expected {expected_arity}"
                )
            if member.key in labels_by_key:
                raise AxisMappingError(
                    f"ResolvedAxisMapping contains duplicate canonical key {member.key!r}"
                )
            if member.labels in key_by_labels:
                previous_key = key_by_labels[member.labels]
                raise AxisMappingError(
                    "ResolvedAxisMapping contains duplicate complete visible label "
                    f"tuple {member.labels!r} for keys {previous_key!r} and {member.key!r}"
                )
            labels_by_key[member.key] = member.labels
            key_by_labels[member.labels] = member.key

        object.__setattr__(
            self,
            "_labels_by_key",
            MappingProxyType(labels_by_key),
        )
        object.__setattr__(
            self,
            "_key_by_labels",
            MappingProxyType(key_by_labels),
        )

    @property
    def label_arity(self) -> int:
        """Number of visible label levels in every member."""
        return len(self.label_columns)

    def labels_for_key(self, key: str) -> tuple[str, ...]:
        """Return the exact complete visible label tuple for ``key``."""
        _require_non_empty_string(key, field_name="canonical key lookup")
        try:
            return self._labels_by_key[key]
        except KeyError:
            raise AxisMappingError(f"Unknown canonical axis key {key!r}") from None

    def key_for_labels(self, labels: tuple[str, ...]) -> str:
        """Return the canonical key for one exact complete label tuple."""
        validated = _resolved_labels(labels, field_name="visible label lookup")
        if len(validated) != self.label_arity:
            raise AxisMappingError(
                f"Visible label lookup has tuple arity {len(validated)}; "
                f"expected {self.label_arity}"
            )
        try:
            return self._key_by_labels[validated]
        except KeyError:
            raise AxisMappingError(
                f"Unknown complete visible label tuple {validated!r}"
            ) from None

    def __iter__(self) -> Iterator[ResolvedAxisMember]:
        return iter(self.members)

    def __len__(self) -> int:
        return len(self.members)
