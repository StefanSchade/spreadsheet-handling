"""Focused contract tests for Trusted Ingress Phase-E slice E1."""

from __future__ import annotations

import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import list_literal_formula, lookup_formula
from spreadsheet_handling.domain.ingress.scalar_admission import (
    OrdinaryScalarAdmissionError,
    admit_ordinary_scalar,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


class _Opaque:
    """Plain unsupported carrier used by the rejection matrix."""


def _callable() -> None:
    return None


def _generator():
    yield 1


@pytest.mark.parametrize(
    "value",
    [
        # String
        "plain",
        "123",
        "=SUM(A1:A2)",
        np.str_("numpy"),
        # Boolean
        True,
        False,
        np.bool_(True),
        # Number
        7,
        1.5,
        np.int64(7),
        np.float32(1.5),
        # Missing
        None,
        "",
        float("nan"),
        np.float64("nan"),
        pd.NA,
        pd.NaT,
        np.datetime64("NaT"),
        # Date
        datetime.date(2026, 8, 11),
        # DateTime
        datetime.datetime(2026, 8, 11, 12, 30),
        datetime.datetime(
            2026,
            8,
            11,
            12,
            30,
            tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
        ),
        pd.Timestamp("2026-08-11T12:30:00+02:00"),
        np.datetime64("2026-08-11", "D"),
        np.datetime64("2026-08-11T12:30:00.123456789", "ns"),
    ],
    ids=[
        "string",
        "numeric-looking-string",
        "formula-looking-string",
        "numpy-string",
        "boolean-true",
        "boolean-false",
        "numpy-boolean",
        "integer",
        "float",
        "numpy-integer",
        "numpy-floating",
        "missing-none",
        "missing-empty-string",
        "missing-float-nan",
        "missing-numpy-nan",
        "missing-pandas-na",
        "missing-pandas-nat",
        "missing-numpy-datetime64-nat",
        "date",
        "datetime",
        "timezone-aware-datetime",
        "pandas-timestamp",
        "numpy-datetime64-day-unit",
        "numpy-datetime64-nanosecond-unit",
    ],
)
def test_admit_ordinary_scalar_accepts_six_category_carriers_without_normalizing(
    value: Any,
) -> None:
    assert admit_ordinary_scalar(value) is value


@pytest.mark.parametrize(
    "value",
    [
        datetime.time(12, 30),
        datetime.timedelta(days=1),
        pd.Timedelta(days=1),
        np.timedelta64(1, "D"),
        np.timedelta64("NaT"),
        b"bytes",
        [1, 2],
        (1, 2),
        {1, 2},
        {"key": "value"},
        list_literal_formula(["a", "b"]),
        lookup_formula(
            source_key_column="code_id",
            lookup_sheet="codes",
            lookup_key_column="id",
            lookup_value_column="label",
        ),
        object(),
        _callable,
        _generator(),
        datetime,
        _Opaque,
        _Opaque(),
    ],
    ids=[
        "time",
        "timedelta",
        "pandas-timedelta",
        "numpy-timedelta64",
        "numpy-timedelta64-nat",
        "bytes",
        "list",
        "tuple",
        "set",
        "dict",
        "list-literal-formula-spec",
        "lookup-formula-spec",
        "arbitrary-object",
        "callable",
        "generator",
        "module",
        "class",
        "opaque-instance",
    ],
)
def test_admit_ordinary_scalar_rejects_unsupported_carriers_with_stable_safe_detail(
    value: Any,
) -> None:
    with pytest.raises(OrdinaryScalarAdmissionError) as excinfo:
        admit_ordinary_scalar(value)

    error = excinfo.value
    assert error.kind == "unsupported_scalar_carrier"
    assert error.carrier_type_name == type(value).__name__
    assert str(error) == (
        "unsupported ordinary scalar carrier of type "
        f"'{error.carrier_type_name}'; expected String, Boolean, Number, Missing, "
        "Date, or DateTime"
    )
    assert vars(error) == {"carrier_type_name": error.carrier_type_name}


def test_complete_admission_rejection_path_does_not_invoke_hostile_protocols() -> None:
    calls: list[str] = []

    class _ProtocolBomb:
        def __getattribute__(self, name: str) -> object:
            if name == "__class__":  # pragma: no cover - must never run
                calls.append("class")
                raise AssertionError("instance __class__ lookup must not run")
            return object.__getattribute__(self, name)

        def __repr__(self) -> str:  # pragma: no cover - must never run
            calls.append("repr")
            raise AssertionError("repr must not run")

        def __str__(self) -> str:  # pragma: no cover - must never run
            calls.append("str")
            raise AssertionError("str must not run")

        def __eq__(self, other: object) -> bool:  # pragma: no cover - must never run
            calls.append("eq")
            raise AssertionError("equality must not run")

        def __hash__(self) -> int:  # pragma: no cover - must never run
            calls.append("hash")
            raise AssertionError("hashing must not run")

        def __iter__(self):  # pragma: no cover - must never run
            calls.append("iter")
            raise AssertionError("iteration must not run")

        def __array__(self, dtype=None, copy=None):  # pragma: no cover - must never run
            calls.append("array")
            raise AssertionError("NumPy conversion must not run")

    bomb = _ProtocolBomb()
    with pytest.raises(OrdinaryScalarAdmissionError) as excinfo:
        admit_ordinary_scalar(bomb)

    error = excinfo.value
    assert error.kind == "unsupported_scalar_carrier"
    assert error.carrier_type_name == "_ProtocolBomb"
    assert str(error).startswith("unsupported ordinary scalar carrier")
    assert vars(error) == {"carrier_type_name": "_ProtocolBomb"}
    assert calls == []


def test_admission_rejects_spoofed_number_without_reading_instance_class() -> None:
    calls: list[str] = []

    class _SpoofedNumber:
        @property
        def __class__(self) -> type[int]:  # pragma: no cover - must never run
            calls.append("class")
            return int

    value = _SpoofedNumber()
    with pytest.raises(OrdinaryScalarAdmissionError) as excinfo:
        admit_ordinary_scalar(value)

    error = excinfo.value
    assert error.kind == "unsupported_scalar_carrier"
    assert error.carrier_type_name == "_SpoofedNumber"
    assert str(error).startswith("unsupported ordinary scalar carrier")
    assert vars(error) == {"carrier_type_name": "_SpoofedNumber"}
    assert calls == []


def test_admission_rejects_spoofed_string_without_equality() -> None:
    calls: list[str] = []

    class _SpoofedString:
        @property
        def __class__(self) -> type[str]:  # pragma: no cover - must never run
            calls.append("class")
            return str

        def __eq__(self, other: object) -> bool:  # pragma: no cover - must never run
            calls.append("eq")
            raise AssertionError("equality must not run for a spoofed String")

    value = _SpoofedString()
    with pytest.raises(OrdinaryScalarAdmissionError) as excinfo:
        admit_ordinary_scalar(value)

    assert excinfo.value.carrier_type_name == "_SpoofedString"
    assert calls == []


def test_admission_rejects_without_reading_raising_instance_class() -> None:
    calls: list[str] = []

    class _RaisingClassLookup:
        def __getattribute__(self, name: str) -> object:
            if name == "__class__":  # pragma: no cover - must never run
                calls.append("class")
                raise AssertionError("instance __class__ lookup must not run")
            return object.__getattribute__(self, name)

    value = _RaisingClassLookup()
    with pytest.raises(OrdinaryScalarAdmissionError) as excinfo:
        admit_ordinary_scalar(value)

    error = excinfo.value
    assert error.kind == "unsupported_scalar_carrier"
    assert error.carrier_type_name == "_RaisingClassLookup"
    assert str(error).startswith("unsupported ordinary scalar carrier")
    assert vars(error) == {"carrier_type_name": "_RaisingClassLookup"}
    assert calls == []


def test_admission_preserves_actual_native_subclass_identity() -> None:
    class _String(str):
        pass

    class _Integer(int):
        pass

    class _Float(float):
        pass

    class _Date(datetime.date):
        pass

    class _DateTime(datetime.datetime):
        pass

    values = (
        _String("text"),
        _String(""),
        _Integer(7),
        _Float(1.5),
        _Date(2026, 8, 11),
        _DateTime(2026, 8, 11, 12, 30),
    )
    for value in values:
        assert admit_ordinary_scalar(value) is value


def test_complete_admission_path_bypasses_hostile_metaclass_type_name() -> None:
    calls: list[str] = []

    class _BombMeta(type):
        def __getattribute__(cls, name: str) -> object:
            if name == "__name__":  # pragma: no cover - must never run
                calls.append("name")
                raise AssertionError("metaclass __name__ lookup must not run")
            return super().__getattribute__(name)

    class _Bomb(metaclass=_BombMeta):
        pass

    value = _Bomb()
    with pytest.raises(OrdinaryScalarAdmissionError) as excinfo:
        admit_ordinary_scalar(value)

    error = excinfo.value
    assert error.kind == "unsupported_scalar_carrier"
    assert error.carrier_type_name == "_Bomb"
    assert str(error) == (
        "unsupported ordinary scalar carrier of type '_Bomb'; expected String, "
        "Boolean, Number, Missing, Date, or DateTime"
    )
    assert vars(error) == {"carrier_type_name": "_Bomb"}
    assert calls == []
