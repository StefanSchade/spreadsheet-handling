"""Contract tests for the Phase-D minimal internal value model.

Proves the invariants `FTR-MINIMAL-INTERNAL-VALUE-MODEL-P4A` requires of its
runtime slice: `is_missing_carrier` recognizes exactly the accepted Missing
carriers (and nothing else); `scalar_category`/`is_supported_scalar` classify
the MVP vocabulary (String/Boolean/Number/Missing) without heuristic string
coercion, with Boolean taking precedence over Number, and reject
`FormulaSpec` Intent and arbitrary Python objects rather than silently
widening a category to fit them.

Also proves `FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` D-T1's own extension:
`datetime.date` classifies as Date; `datetime.datetime`/`pandas.Timestamp`/
non-`NaT` `numpy.datetime64` (any unit, naive or timezone-aware) classify as
DateTime, with DateTime checked before Date (subclass-ordering hazard);
`numpy.datetime64('NaT')` classifies as Missing through its own explicit
branch; `numpy.timedelta64`, `datetime.time`, `datetime.timedelta`, and
`pandas.Timedelta` remain uniformly unsupported, as non-regressions.
"""
from __future__ import annotations

import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import list_literal_formula
from spreadsheet_handling.core.scalar_values import (
    ScalarCategory,
    UnsupportedScalarError,
    is_missing_carrier,
    is_supported_scalar,
    scalar_category,
)

pytestmark = [
    pytest.mark.ftr("FTR-MINIMAL-INTERNAL-VALUE-MODEL-P4A"),
    pytest.mark.ftr("FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A"),
]


class _Opaque:
    """A plain object with no special behavior, used as a rejection probe."""


def _generator():
    yield 1


# ---------------------------------------------------------------------------
# is_missing_carrier -- D1
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        (None, True),
        ("", True),
        (float("nan"), True),
        (np.nan, True),
        (pd.NA, True),
        (pd.NaT, True),
        ("nan", False),  # a literal domain string, not a missing carrier
        ("None", False),
        (0, False),
        (0.0, False),
        (False, False),
        (True, False),
        ("x", False),
        ([], False),  # pd.isna raises on array-likes; caught, not missing
        ({}, False),
        # BUG-NUMPY-TIMEDELTA64-NUMBER-MISCLASSIFICATION-P4A: numpy.timedelta64
        # is explicitly excluded from the bounded np.generic dispatch, so its
        # NaT form must not be recognized as Missing (Duration is unsupported,
        # not a Missing-adjacent category).
        (np.timedelta64("NaT"), False),
        (np.timedelta64(1, "D"), False),
    ],
    ids=[
        "none", "empty-string", "float-nan", "numpy-nan", "pd-NA", "pd-NaT",
        "literal-nan-string", "literal-none-string", "int-zero", "float-zero",
        "false", "true", "plain-string", "empty-list", "empty-dict",
        "numpy-timedelta64-nat", "numpy-timedelta64-days",
    ],
)
def test_is_missing_carrier_matches_accepted_contract(value: Any, expected: bool) -> None:
    assert is_missing_carrier(value) is expected


def test_is_missing_carrier_idempotent_on_every_supported_case() -> None:
    for value in (None, "", float("nan"), np.nan, pd.NA, pd.NaT, "nan", 0, False, "x"):
        first = is_missing_carrier(value)
        second = is_missing_carrier(value)
        assert first == second


def test_is_missing_carrier_safe_on_pathological_objects() -> None:
    # Must not raise for any non-carrier object; the try/except around
    # pandas.isna must absorb TypeError/ValueError, not propagate it.
    assert is_missing_carrier(_Opaque()) is False
    assert is_missing_carrier(lambda: None) is False
    assert is_missing_carrier(pd) is False
    assert is_missing_carrier(_generator()) is False


class _CustomConversionError(Exception):
    """A domain-specific exception type, deliberately not TypeError/ValueError."""


class _ArrayLikeBomb:
    """A non-hostile object implementing NumPy's documented `__array__`
    array-conversion protocol whose conversion fails with an exception type
    the old `except (TypeError, ValueError)` guard around `pandas.isna` did
    not catch (Independent Review 001, finding IVM-REVIEW-F1). Tracks
    whether `__array__` was actually invoked so the test can assert the
    bounded-dispatch fix never reaches it at all, not merely that it
    survives being reached.
    """

    def __init__(self) -> None:
        self.array_called = False

    def __array__(self, dtype=None):  # pragma: no cover - must never run
        self.array_called = True
        raise _CustomConversionError("must never be called")


def test_is_missing_carrier_never_invokes_array_protocol_on_unrecognized_object() -> None:
    # Regression for IVM-REVIEW-F1: pandas.isna on an arbitrary object can
    # invoke that object's own __array__ and propagate whatever it raises.
    # The bounded-dispatch fix must never call pandas.isna on an object
    # outside the accepted scalar-carrier shapes (int/float/numpy.generic),
    # so __array__ must never even be invoked.
    bomb = _ArrayLikeBomb()
    assert is_missing_carrier(bomb) is False
    assert bomb.array_called is False


def test_is_supported_scalar_never_propagates_array_conversion_exception() -> None:
    # is_supported_scalar's own docstring promises "Never raises" -- this
    # must hold for the array-protocol case, not only for the cases the
    # original test suite exercised.
    bomb = _ArrayLikeBomb()
    assert is_supported_scalar(bomb) is False
    assert bomb.array_called is False


def test_scalar_category_rejects_array_like_bomb_with_unsupported_scalar_error() -> None:
    # scalar_category must still produce its own documented diagnostic
    # (UnsupportedScalarError), not let the object's __array__ exception
    # leak through.
    bomb = _ArrayLikeBomb()
    with pytest.raises(UnsupportedScalarError):
        scalar_category(bomb)
    assert bomb.array_called is False


# ---------------------------------------------------------------------------
# scalar_category / is_supported_scalar -- classification, not conversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected_category",
    [
        # String
        ("hello", "string"),
        ("1", "string"),  # numeric-looking string stays a string
        ("true", "string"),  # boolean-looking string stays a string
        ("false", "string"),
        ("2026-08-09", "string"),  # date-looking string stays a string
        ("=SUM(A1:A2)", "string"),  # formula-looking string stays a string
        ("nan", "string"),  # literal text, not a missing carrier
        ("", "missing"),
        # Boolean (checked before Number)
        (True, "boolean"),
        (False, "boolean"),
        (np.bool_(True), "boolean"),
        (np.bool_(False), "boolean"),
        # Number
        (0, "number"),
        (-3, "number"),
        (1.5, "number"),
        (np.int64(7), "number"),
        (np.float64(1.5), "number"),
        (np.float32(1.5), "number"),
        # Missing
        (None, "missing"),
        (float("nan"), "missing"),
        (np.nan, "missing"),
        (pd.NA, "missing"),
        (pd.NaT, "missing"),
    ],
    ids=[
        "string-plain", "string-numeric-looking", "string-true-looking",
        "string-false-looking", "string-date-looking", "string-formula-looking",
        "string-nan-looking", "empty-string-is-missing",
        "bool-true", "bool-false", "numpy-bool-true", "numpy-bool-false",
        "int-zero", "int-negative", "float", "numpy-int64", "numpy-float64",
        "numpy-float32", "none", "float-nan", "numpy-nan", "pd-NA", "pd-NaT",
    ],
)
def test_scalar_category_classifies_mvp_vocabulary(value: Any, expected_category: str) -> None:
    assert scalar_category(value) == expected_category
    assert is_supported_scalar(value) is True


def test_scalar_category_never_mistakes_bool_for_number() -> None:
    # bool is a subclass of int in Python; Boolean must win.
    assert scalar_category(True) == "boolean"
    assert scalar_category(False) == "boolean"
    assert scalar_category(np.bool_(True)) == "boolean"


def test_scalar_category_is_pure_classification_not_coercion() -> None:
    # A supported value passes through unexamined in content and unchanged
    # in identity -- scalar_category never mutates or reinterprets it.
    original = "007"
    assert scalar_category(original) == "string"
    assert original == "007"  # unchanged; never promoted to a number


def test_scalar_category_vocabulary_is_exactly_six_categories() -> None:
    # FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A D-T1 section 15: the closed
    # vocabulary is exactly string/boolean/number/missing/date/datetime --
    # no time, duration, formula, or list member.
    assert set(ScalarCategory.__args__) == {
        "string", "boolean", "number", "missing", "date", "datetime",
    }


@pytest.mark.parametrize(
    "value",
    [
        np.timedelta64(1, "D"),
        np.timedelta64(500, "ns"),
        np.timedelta64("NaT"),
    ],
    ids=["timedelta64-days", "timedelta64-nanoseconds", "timedelta64-nat"],
)
def test_scalar_category_rejects_numpy_timedelta64_without_number_misclassification(
    value: Any,
) -> None:
    # Regression for BUG-NUMPY-TIMEDELTA64-NUMBER-MISCLASSIFICATION-P4A
    # (independently discovered as DTVM-REVIEW-F1): numpy.timedelta64
    # subclasses numpy.signedinteger/numpy.integer, so without an explicit
    # exclusion it silently classifies as "number" -- a real accepted
    # carrier silently becoming domain Number semantics, stripped of its
    # unit. Duration is not a supported category; every numpy.timedelta64
    # value, NaT or not, must raise UnsupportedScalarError uniformly rather
    # than partially "number" and partially "missing".
    with pytest.raises(UnsupportedScalarError) as excinfo:
        scalar_category(value)
    assert excinfo.value.value_type_name == "timedelta64"
    assert is_supported_scalar(value) is False
    # The NaT form must not be recognized as Missing either -- an unsupported
    # category rejects all its instances, it does not partially fold its
    # missing-shaped instances into a different, unrelated category.
    assert is_missing_carrier(value) is False


def test_scalar_category_still_accepts_numpy_datetime64_nat_as_missing() -> None:
    # Non-regression from BUG-NUMPY-TIMEDELTA64-NUMBER-MISCLASSIFICATION-P4A:
    # numpy.datetime64('NaT') classifies as Missing. As of D-T1
    # (FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A), this is no longer an
    # accidental side effect of the generic np.generic dispatch -- it goes
    # through is_missing_carrier's own explicit numpy.datetime64 branch (see
    # test_is_missing_carrier_numpy_datetime64_explicit_branch below), which
    # this test pins at the scalar_category level too.
    assert is_missing_carrier(np.datetime64("NaT")) is True
    assert scalar_category(np.datetime64("NaT")) == "missing"


def test_scalar_category_still_rejects_datetime_timedelta_and_pandas_timedelta() -> None:
    # Non-regression: these Duration carriers were already, correctly,
    # unsupported and are unaffected by this fix -- Duration is not added as
    # a supported category by this BUG.
    for value in (datetime.timedelta(days=1), pd.Timedelta(days=1)):
        with pytest.raises(UnsupportedScalarError):
            scalar_category(value)
        assert is_supported_scalar(value) is False


def test_scalar_category_still_rejects_datetime_time() -> None:
    # Non-regression / explicit deferral: Time is not added to the
    # vocabulary by D-T1 (FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A section 9).
    value = datetime.time(12, 30)
    with pytest.raises(UnsupportedScalarError) as excinfo:
        scalar_category(value)
    assert excinfo.value.value_type_name == "time"
    assert is_supported_scalar(value) is False


# ---------------------------------------------------------------------------
# scalar_category -- Date/DateTime (FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A, D-T1)
# ---------------------------------------------------------------------------


def test_scalar_category_classifies_date_and_datetime() -> None:
    assert scalar_category(datetime.date(2026, 8, 9)) == "date"
    assert is_supported_scalar(datetime.date(2026, 8, 9)) is True

    assert scalar_category(datetime.datetime(2026, 8, 9, 12, 0, 0)) == "datetime"
    assert is_supported_scalar(datetime.datetime(2026, 8, 9, 12, 0, 0)) is True

    assert scalar_category(pd.Timestamp("2026-08-09")) == "datetime"
    assert is_supported_scalar(pd.Timestamp("2026-08-09")) is True


def test_scalar_category_never_mistakes_datetime_for_date() -> None:
    # datetime.datetime subclasses datetime.date, and pandas.Timestamp
    # subclasses datetime.datetime -- DateTime must win the ordering check
    # for both, mirroring Boolean-before-Number.
    assert scalar_category(datetime.datetime(2026, 8, 9)) == "datetime"
    assert scalar_category(pd.Timestamp("2026-08-09")) == "datetime"
    # A genuine midnight DateTime is not reclassified as Date merely because
    # its time-of-day happens to be midnight -- no time-of-day heuristic.
    assert scalar_category(datetime.datetime(2026, 8, 9, 0, 0, 0)) == "datetime"
    assert scalar_category(pd.Timestamp("2026-08-09 00:00:00")) == "datetime"


@pytest.mark.parametrize(
    "value",
    [
        np.datetime64("2026-08-09", "D"),
        np.datetime64("2026-08-09T12:34", "m"),
        np.datetime64("2026-08-09T12:34:56.123456", "us"),
        np.datetime64("2026-08-09T12:34:56.123456789", "ns"),
    ],
    ids=["unit-D", "unit-m", "unit-us", "unit-ns"],
)
def test_scalar_category_classifies_numpy_datetime64_as_datetime_for_every_unit(
    value: Any,
) -> None:
    assert scalar_category(value) == "datetime"
    assert is_supported_scalar(value) is True


def test_scalar_category_does_not_infer_date_from_numpy_datetime64_day_unit() -> None:
    # Pin explicitly: unit "D" does NOT produce Date. Day-precision storage
    # is genuinely ambiguous between "authored as a date" and "datetime
    # truncated to day granularity" (section 8's [DECIDED] rule) -- no
    # carrier-internal heuristic distinguishes them.
    assert scalar_category(np.datetime64("2026-08-09", "D")) == "datetime"


def test_is_missing_carrier_numpy_datetime64_explicit_branch() -> None:
    # Closes the remaining numpy.datetime64 half of IVM-REVIEW-F7: NaT is
    # Missing through its own explicit branch; a non-NaT value is not.
    assert is_missing_carrier(np.datetime64("NaT")) is True
    assert is_missing_carrier(np.datetime64("2026-08-09")) is False
    assert is_missing_carrier(np.datetime64("2026-08-09T12:34", "m")) is False


def test_scalar_category_classifies_timezone_aware_datetime_and_timestamp_as_datetime() -> None:
    offset = datetime.timezone(datetime.timedelta(hours=2))
    aware_dt = datetime.datetime(2026, 8, 9, 10, 30, tzinfo=offset)
    aware_ts = pd.Timestamp("2026-08-09T10:30:00+02:00")

    assert scalar_category(aware_dt) == "datetime"
    assert scalar_category(aware_ts) == "datetime"
    assert is_supported_scalar(aware_dt) is True
    assert is_supported_scalar(aware_ts) is True

    # Classification must not mutate/normalize the carrier -- tzinfo/offset
    # remains present after classification (no stripping, no naive
    # conversion, no UTC assumption).
    assert aware_dt.tzinfo is not None
    assert aware_dt.utcoffset() == datetime.timedelta(hours=2)
    assert aware_ts.tzinfo is not None
    assert aware_ts.utcoffset() == datetime.timedelta(hours=2)


def test_scalar_category_rejects_formula_spec_intent() -> None:
    # A FormulaSpec is authored backend-neutral Intent, not payload; it must
    # never be silently classified as a scalar category.
    spec = list_literal_formula(["a", "b"])
    with pytest.raises(UnsupportedScalarError):
        scalar_category(spec)
    assert is_supported_scalar(spec) is False


@pytest.mark.parametrize(
    "value",
    [
        [1, 2, 3],
        {"a": 1},
        {1, 2},
        (1, 2),
        _generator(),
        lambda: None,
        pd,  # a module
        _Opaque(),
    ],
    ids=[
        "list", "dict", "set", "tuple", "generator", "callable", "module",
        "opaque-object",
    ],
)
def test_scalar_category_rejects_arbitrary_objects_with_safe_diagnostic(value: Any) -> None:
    with pytest.raises(UnsupportedScalarError) as excinfo:
        scalar_category(value)
    # The diagnostic names only the type, never the value's own repr/str.
    assert type(value).__name__ in str(excinfo.value)
    assert is_supported_scalar(value) is False


def test_unsupported_scalar_error_diagnostic_never_calls_value_repr() -> None:
    class _Bomb:
        def __repr__(self) -> str:  # pragma: no cover - must never run
            raise AssertionError("repr() must not be called for a rejection diagnostic")

        def __str__(self) -> str:  # pragma: no cover - must never run
            raise AssertionError("str() must not be called for a rejection diagnostic")

        def __eq__(self, other: object) -> bool:  # pragma: no cover - must never run
            raise AssertionError("__eq__ must not be called for a rejection diagnostic")

        __hash__ = None  # type: ignore[assignment]

    with pytest.raises(UnsupportedScalarError):
        scalar_category(_Bomb())


def test_scalar_category_deterministic_and_idempotent_for_every_supported_case() -> None:
    values = (
        "hello", True, 1, 1.5, None, "", np.int64(2), np.bool_(True),
        datetime.date(2026, 8, 9), datetime.datetime(2026, 8, 9, 12, 0, 0),
        pd.Timestamp("2026-08-09"), np.datetime64("2026-08-09"),
    )
    for value in values:
        assert scalar_category(value) == scalar_category(value)
