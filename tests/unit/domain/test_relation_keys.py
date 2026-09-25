"""Contract tests for the private Domain relation-key identity owner."""

from __future__ import annotations

import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest

from spreadsheet_handling.domain.relation_keys import (
    is_relation_key_eligible,
    relation_key_identity,
    relation_keys_equal,
)

pytestmark = pytest.mark.ftr("DMC-RELKEY-C0-S1")


def test_equal_exact_string_keys_share_identity() -> None:
    assert relation_keys_equal(("alpha",), ("alpha",))
    assert relation_key_identity("alpha") == relation_key_identity("alpha")


def test_string_whitespace_is_relation_key_payload() -> None:
    assert not relation_keys_equal((" 1 ",), ("1",))


def test_category_is_part_of_relation_key_identity() -> None:
    assert not relation_keys_equal((1,), ("1",))
    assert not relation_keys_equal((True,), (1,))


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (1, 1.0),
        (np.int64(1), 1),
    ],
)
def test_equal_numbers_are_carrier_independent(left: Any, right: Any) -> None:
    assert relation_keys_equal((left,), (right,))
    assert relation_key_identity(left) == relation_key_identity(right)
    assert hash(relation_key_identity(left)) == hash(relation_key_identity(right))


def test_number_identity_uses_exact_represented_values_without_promotion() -> None:
    assert not relation_keys_equal((np.float32(0.1),), (0.1,))
    assert not relation_keys_equal((np.int64(2**53 + 1),), (np.float64(2**53),))


def test_longdouble_identity_does_not_round_trip_through_float() -> None:
    assert not relation_keys_equal((np.longdouble("0.1"),), (0.1,))


@pytest.mark.parametrize("value", [None, "", float("nan"), pd.NA, pd.NaT, np.datetime64("NaT")])
def test_missing_carriers_are_ineligible_relation_keys(value: Any) -> None:
    assert not is_relation_key_eligible(value)
    assert relation_key_identity(value) is None
    assert not relation_keys_equal((value,), (value,))


def test_equal_keys_always_have_equal_hashes() -> None:
    equal_pairs = (
        ("alpha", "alpha"),
        (1, 1.0),
        (np.int64(1), 1),
        (
            np.datetime64("2020-01-01T12:30:00.123456"),
            datetime.datetime(2020, 1, 1, 12, 30, 0, 123456),
        ),
    )
    for left, right in equal_pairs:
        left_identity = relation_key_identity(left)
        right_identity = relation_key_identity(right)
        assert left_identity == right_identity
        assert hash(left_identity) == hash(right_identity)


def test_equal_naive_datetime_carriers_form_one_transitive_identity() -> None:
    numpy_value = np.datetime64("2020-01-01T12:30:00.123456")
    pandas_value = pd.Timestamp("2020-01-01T12:30:00.123456")
    python_value = datetime.datetime(2020, 1, 1, 12, 30, 0, 123456)
    identities = {
        relation_key_identity(value) for value in (numpy_value, pandas_value, python_value)
    }
    assert len(identities) == 1


def test_aware_datetimes_compare_by_exact_utc_instant() -> None:
    timestamp = pd.Timestamp("2020-01-01T12:00:00.123456+01:00")
    datetime_value = datetime.datetime(
        2020,
        1,
        1,
        11,
        0,
        0,
        123456,
        tzinfo=datetime.timezone.utc,
    )
    assert relation_keys_equal((timestamp,), (datetime_value,))


def test_aware_and_naive_datetimes_are_distinct() -> None:
    aware = datetime.datetime(2020, 1, 1, 12, tzinfo=datetime.timezone.utc)
    naive = datetime.datetime(2020, 1, 1, 12)
    assert not relation_keys_equal((aware,), (naive,))


def test_date_and_day_precision_datetime_are_distinct_categories() -> None:
    assert not relation_keys_equal((datetime.date(2020, 1, 1),), (np.datetime64("2020-01-01"),))


def test_composite_relation_keys_are_ordered_and_require_eligible_components() -> None:
    assert relation_keys_equal(("alpha", 1), ("alpha", 1.0))
    assert not relation_keys_equal(("alpha", 1), (1, "alpha"))
    assert relation_key_identity("alpha", None) is None
    assert not relation_keys_equal(("alpha", None), ("alpha", None))
