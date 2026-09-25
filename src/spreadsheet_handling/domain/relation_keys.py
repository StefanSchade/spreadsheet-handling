"""Private Domain identity for in-memory relation keys.

This module owns the deliberately narrow rule used by relation resolution and
relation validation.  It consumes the Core scalar classifier but does not
extend it or normalize stored scalar carriers.  Missing values are ineligible;
all other admitted scalar values receive a category-tagged identity.  The same
opaque identity supplies both equality and hashing, so collection mechanics
cannot disagree with relation-key comparison.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import numpy as np
import pandas as pd

from spreadsheet_handling.core.scalar_values import scalar_category

_DAY_MICROSECONDS = 86_400_000_000
_EPOCH_ORDINAL = datetime.date(1970, 1, 1).toordinal()
_FIXED_DATETIME_UNITS: dict[str, Fraction] = {
    "W": Fraction(7),
    "D": Fraction(1),
    "h": Fraction(1, 24),
    "m": Fraction(1, 1_440),
    "s": Fraction(1, 86_400),
    "ms": Fraction(1, 86_400_000),
    "us": Fraction(1, 86_400_000_000),
    "ns": Fraction(1, 86_400_000_000_000),
    "ps": Fraction(1, 86_400_000_000_000_000),
    "fs": Fraction(1, 86_400_000_000_000_000_000),
    "as": Fraction(1, 86_400_000_000_000_000_000_000),
}


@dataclass(frozen=True)
class RelationKeyIdentity:
    """Hashable, category-tagged identity for one ordered relation key.

    The stored tokens are private mechanics.  Consumers use this value as a
    map/set key or compare it directly; they must not recreate tokens from
    raw carriers, because native equality, NumPy promotion, and pandas dtype
    rules do not implement the Domain relation-key contract.
    """

    _components: tuple[tuple[object, ...], ...]


def is_relation_key_eligible(*components: Any) -> bool:
    """Whether every supplied scalar component can participate in a key.

    A call with one argument checks a scalar key; multiple arguments describe
    one ordered composite key.  Unsupported values are rejected by the Core
    scalar-admission authority rather than coerced here.
    """
    return all(scalar_category(component) != "missing" for component in components)


def relation_key_identity(*components: Any) -> RelationKeyIdentity | None:
    """Return one shared identity for an eligible scalar or composite key.

    ``None`` means at least one component is Missing and therefore cannot be
    a relation key.  Strings remain exact, category is part of each token, and
    DateTime coordinates use exact arithmetic rather than carrier equality or
    NumPy unit promotion.  Unsupported values raise the classifier's error.
    """
    identities: list[tuple[object, ...]] = []
    for component in components:
        category = scalar_category(component)
        if category == "missing":
            return None
        identities.append(_relation_key_component_identity(component, category))
    return RelationKeyIdentity(tuple(identities))


def relation_keys_equal(left: tuple[Any, ...], right: tuple[Any, ...]) -> bool:
    """Compare two ordered relation keys through their shared identities."""
    left_identity = relation_key_identity(*left)
    right_identity = relation_key_identity(*right)
    if left_identity is None or right_identity is None:
        return False
    return left_identity == right_identity


def _relation_key_component_identity(component: Any, category: str) -> tuple[object, ...]:
    if category == "string":
        return ("string", component)
    if category == "boolean":
        return ("boolean", bool(component))
    if category == "number":
        return ("number", *_number_identity(component))
    if category == "date":
        return ("date", component.toordinal())
    if category == "datetime":
        awareness, coordinate = _datetime_identity(component)
        return ("datetime", awareness, coordinate)
    raise AssertionError(f"unexpected eligible scalar category: {category}")


def _number_identity(value: Any) -> tuple[object, ...]:
    """Build an exact mathematical Number token without dtype promotion."""
    if isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
        return ("finite", int(value), 1)
    if np.isinf(value):
        sign = 1 if value > 0 else -1
        return ("infinity", sign)
    numerator, denominator = value.as_integer_ratio()
    return ("finite", int(numerator), int(denominator))


def _datetime_identity(value: Any) -> tuple[str, Fraction]:
    """Return the explicit naive-wall-clock or aware-UTC relation coordinate."""
    if isinstance(value, np.datetime64):
        return "naive", _numpy_datetime_coordinate(value)
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            return "naive", _numpy_datetime_coordinate(value.asm8)
        return "aware", _numpy_datetime_coordinate(value.asm8)
    if _is_aware_datetime(value):
        coordinate = _python_datetime_coordinate(value)
        offset = value.utcoffset()
        assert offset is not None
        return "aware", coordinate - _timedelta_as_days(offset)
    return "naive", _python_datetime_coordinate(value)


def _is_aware_datetime(value: datetime.datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _python_datetime_coordinate(value: datetime.datetime) -> Fraction:
    day_offset = value.date().toordinal() - _EPOCH_ORDINAL
    microseconds = (
        (value.hour * 60 + value.minute) * 60 + value.second
    ) * 1_000_000 + value.microsecond
    return Fraction(day_offset) + Fraction(microseconds, _DAY_MICROSECONDS)


def _timedelta_as_days(value: datetime.timedelta) -> Fraction:
    microseconds = (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds
    return Fraction(microseconds, _DAY_MICROSECONDS)


def _numpy_datetime_coordinate(value: np.datetime64) -> Fraction:
    """Derive a DateTime coordinate from raw ticks, never unit promotion.

    ``datetime64[Y]`` and ``datetime64[M]`` are calendar units, so their raw
    ticks are converted to an exact first-of-month day coordinate.  All fixed
    units retain their full precision as a rational number of days.
    """
    unit, multiplier = np.datetime_data(value.dtype)
    raw_ticks = int(value.view("i8"))
    if unit in {"Y", "M"}:
        months_since_epoch = raw_ticks * multiplier
        if unit == "Y":
            months_since_epoch *= 12
        year, month_index = divmod(1970 * 12 + months_since_epoch, 12)
        return Fraction(_days_since_epoch(year, month_index + 1, 1))
    fixed_unit_days = _FIXED_DATETIME_UNITS.get(unit)
    if fixed_unit_days is None:
        raise ValueError(f"unsupported datetime64 unit for relation key: {unit}")
    return Fraction(raw_ticks * multiplier) * fixed_unit_days


def _days_since_epoch(year: int, month: int, day: int) -> int:
    """Return a proleptic-Gregorian day offset without narrowing NumPy dates."""
    adjusted_year = year - 1 if month <= 2 else year
    era = adjusted_year // 400
    year_of_era = adjusted_year - era * 400
    month_index = month + 9 if month <= 2 else month - 3
    day_of_year = (153 * month_index + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146_097 + day_of_era - 719_468
