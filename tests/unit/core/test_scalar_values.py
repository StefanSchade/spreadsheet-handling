"""Contract tests for the Phase-D minimal internal value model.

Proves the invariants `FTR-MINIMAL-INTERNAL-VALUE-MODEL-P4A` requires of its
runtime slice: `is_missing_carrier` recognizes exactly the accepted Missing
carriers (and nothing else); `scalar_category`/`is_supported_scalar` classify
the MVP vocabulary (String/Boolean/Number/Missing) without heuristic string
coercion, with Boolean taking precedence over Number, and reject dates,
`FormulaSpec` Intent, and arbitrary Python objects rather than silently
widening a category to fit them.
"""
from __future__ import annotations

import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import list_literal_formula
from spreadsheet_handling.core.scalar_values import (
    UnsupportedScalarError,
    is_missing_carrier,
    is_supported_scalar,
    scalar_category,
)

pytestmark = pytest.mark.ftr("FTR-MINIMAL-INTERNAL-VALUE-MODEL-P4A")


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
    ],
    ids=[
        "none", "empty-string", "float-nan", "numpy-nan", "pd-NA", "pd-NaT",
        "literal-nan-string", "literal-none-string", "int-zero", "float-zero",
        "false", "true", "plain-string", "empty-list", "empty-dict",
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


@pytest.mark.parametrize(
    "value",
    [
        datetime.date(2026, 8, 9),
        datetime.datetime(2026, 8, 9, 12, 0, 0),
        pd.Timestamp("2026-08-09"),
    ],
    ids=["date", "datetime", "pandas-timestamp"],
)
def test_scalar_category_rejects_date_time_without_silent_coercion(value: Any) -> None:
    # Date/Time is an explicit MVP deferral: it must never be silently
    # promoted to String or Number to fit this slice's category set.
    with pytest.raises(UnsupportedScalarError):
        scalar_category(value)
    assert is_supported_scalar(value) is False


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
    for value in ("hello", True, 1, 1.5, None, "", np.int64(2), np.bool_(True)):
        assert scalar_category(value) == scalar_category(value)
