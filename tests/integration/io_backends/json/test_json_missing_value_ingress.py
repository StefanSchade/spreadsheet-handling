"""JSON directory-ingress Missing-identity slice.

Guards `BUG-JSON-INGRESS-MISSING-IDENTITY-P4A`: `JSONBackend.read_multi`
read every cell through `pandas.read_json(..., dtype=str)`, which on
pandas 2.x applies `astype(str)` to the parsed column *before* the
backend's own `df.where(pd.notnull(df), "")` normalization can run. An
explicit JSON `null` therefore arrived as the literal domain string
`"None"` and a structurally absent field as the literal domain string
`"nan"` -- both `pandas.notnull`-true, so the Missing normalization could
no longer see them, and the Core value model
(`core.scalar_values.is_missing_carrier`) correctly refused to recognize
them as Missing.

These tests assert the ingress contract from the *consumer* side, at the
real `read_json_dir` boundary, over hand-authored JSON: `write_json_dir`
never emits `null` or omits a key, so the defect is only reachable through
externally authored input.

They pin both halves of the contract, which must not be traded off against
each other:

* Missing carriers (`null`, absent) normalize to the canonical `""`.
* The legitimate domain strings `"None"` and `"nan"` stay themselves --
  the fix must not be a post-hoc string replacement.

The surrounding string-substrate contract (no type guessing, no date
inference, nested payloads stringified rather than decoded) is pinned here
too, since the fix touches the call that provides it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spreadsheet_handling.core.scalar_values import is_missing_carrier
from spreadsheet_handling.io_backends.json_backend import read_json_dir

pytestmark = pytest.mark.ftr("BUG-JSON-INGRESS-MISSING-IDENTITY-P4A")


def _read_one(tmp_path: Path, payload: str, *, stem: str = "rows"):
    """Write `payload` as the only JSON file in a directory and read it back."""
    in_dir = tmp_path / "in"
    in_dir.mkdir(exist_ok=True)
    (in_dir / f"{stem}.json").write_text(payload, encoding="utf-8")
    return read_json_dir(str(in_dir))[stem]


def test_explicit_null_reads_as_canonical_missing(tmp_path: Path) -> None:
    """An explicit JSON `null` is Missing, never the domain string `"None"`."""
    df = _read_one(tmp_path, '[{"id": "a", "value": null}]')

    value = df.iloc[0]["value"]
    assert value == ""
    assert value != "None"
    assert is_missing_carrier(value)


def test_structurally_absent_field_reads_as_canonical_missing(tmp_path: Path) -> None:
    """A key absent from one record is Missing, never the domain string `"nan"`."""
    df = _read_one(tmp_path, '[{"id": "a"}, {"id": "b", "value": "x"}]')

    absent = df.iloc[0]["value"]
    assert absent == ""
    assert absent != "nan"
    assert is_missing_carrier(absent)

    # the sibling record's real value is untouched
    assert df.iloc[1]["value"] == "x"


def test_all_null_column_reads_as_canonical_missing(tmp_path: Path) -> None:
    """A column whose every value is `null` normalizes to `""` throughout."""
    df = _read_one(tmp_path, '[{"a": null}, {"a": null}]')

    assert list(df["a"]) == ["", ""]
    assert all(is_missing_carrier(v) for v in df["a"])


def test_literal_none_string_is_preserved_as_domain_value(tmp_path: Path) -> None:
    """`"None"` is a legitimate domain string and must survive ingress."""
    df = _read_one(tmp_path, '[{"value": "None"}]')

    value = df.iloc[0]["value"]
    assert value == "None"
    assert not is_missing_carrier(value)


def test_literal_nan_string_is_preserved_as_domain_value(tmp_path: Path) -> None:
    """`"nan"` is a legitimate domain string and must survive ingress.

    Pinned explicitly because the un-coerced pandas JSON parser *does*
    coerce the strings `"nan"`/`"NaN"` to a float NaN -- any fix that
    derives its Missing mask from such a read would silently destroy this
    value.
    """
    df = _read_one(tmp_path, '[{"value": "nan"}, {"value": "NaN"}]')

    assert list(df["value"]) == ["nan", "NaN"]
    assert not any(is_missing_carrier(v) for v in df["value"])


def test_missing_and_literal_missing_lookalikes_coexist_in_one_column(
    tmp_path: Path,
) -> None:
    """The discriminating case: Missing and its look-alike strings together.

    A post-hoc "replace `"None"`/`"nan"` with `""`" fix passes every
    single-case test above and fails here.
    """
    df = _read_one(
        tmp_path,
        '[{"v": null}, {"v": "None"}, {"v": "nan"}, {"v": "real"}, {"w": "x"}]',
    )

    assert list(df["v"]) == ["", "None", "nan", "real", ""]


def test_ordinary_scalars_retain_string_ingress_semantics(tmp_path: Path) -> None:
    """Non-missing scalars keep the existing visible-string substrate.

    These exact renderings are the pre-existing `dtype=str` contract; the
    Missing fix must not perturb any of them.
    """
    df = _read_one(
        tmp_path,
        '[{"s": "hello", "i": 3, "neg": -7, "f": 3.14, "big_f": 1e20,'
        ' "t": true, "f_": false, "empty": "",'
        ' "big_i": 9007199254740993, "negz": -0.0}]',
    )

    row = df.iloc[0]
    assert row["s"] == "hello"
    assert row["i"] == "3"
    assert row["neg"] == "-7"
    assert row["f"] == "3.14"
    assert row["big_f"] == "1e+20"
    assert row["t"] == "True"
    assert row["f_"] == "False"
    assert row["empty"] == ""
    assert row["big_i"] == "9007199254740993"
    assert row["negz"] == "-0.0"
    assert all(isinstance(v, str) for v in row)


def test_date_looking_strings_are_not_inferred_as_dates(tmp_path: Path) -> None:
    """`convert_dates=False` stays in force -- no opportunistic date inference.

    Both a plain ISO date and an ISO datetime stay verbatim strings, and a
    column *named* like a date (pandas' own `keep_default_dates` heuristic
    keys on names such as `date`) is not special-cased either.
    """
    df = _read_one(
        tmp_path,
        '[{"date": "2026-08-09", "timestamp": "2026-08-09T10:30:00",'
        ' "modified_at": "2026-12-31"}]',
    )

    row = df.iloc[0]
    assert row["date"] == "2026-08-09"
    assert row["timestamp"] == "2026-08-09T10:30:00"
    assert row["modified_at"] == "2026-12-31"
    assert all(isinstance(v, str) for v in row)


def test_nested_payload_still_stringifies_rather_than_decoding(tmp_path: Path) -> None:
    """Option B non-regression (`FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` 27.11).

    `read_multi` remains unwired from the `$date`/`$datetime` decoder: a
    nested object cell arrives as a stringified Python repr, not a native
    value and not a `dict`.
    """
    df = _read_one(tmp_path, '[{"a": {"$date": "2026-08-09"}, "b": "x"}]')

    value = df.iloc[0]["a"]
    assert isinstance(value, str)
    assert value == "{'$date': '2026-08-09'}"
    assert df.iloc[0]["b"] == "x"
