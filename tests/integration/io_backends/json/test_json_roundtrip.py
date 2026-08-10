"""JSON backend integration slice.

Verifies the real JSON directory writer and reader preserve visible tabular
frames through a filesystem roundtrip.

Also covers `FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` D-T2.2/D-T2.3's accepted
structured-persistence contract (section 27.9/27.12/27.13): `write_json_dir`
gains a persistence-local `_json_temporal_default` encoder (`pandas.NaT`
checked first, then `pandas.Timestamp`, then plain `datetime.datetime`, then
`datetime.date`) so a Date/DateTime column no longer raises `TypeError`,
using reserved `$date`/`$datetime` single-key envelopes; a symmetric
`_json_temporal_object_hook` decoder exists and is exercised here directly,
at the codec level only -- `read_json_dir`/`JSONBackend.read_multi` is
deliberately, and permanently for this slice, *not* wired to it (Option B).
"""

from __future__ import annotations

import datetime
import json

import pandas as pd
import pytest
from pathlib import Path

from spreadsheet_handling.io_backends.json_backend import (
    _json_temporal_default,
    _json_temporal_object_hook,
    read_json_dir,
    write_json_dir,
)

pytestmark = pytest.mark.ftr("FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A")


def test_json_roundtrip(tmp_path: Path):
    frames = {
        "products": pd.DataFrame([{"id":"P-1","name":"Alpha"}, {"id":"P-2","name":"Beta"}]),
        "branches": pd.DataFrame([{"branch_id":"B-1","city":"X"}]),
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))
    back = read_json_dir(str(out))
    assert set(back.keys()) == {"products","branches"}
    assert list(back["products"].columns) == ["id","name"]
    assert back["products"].iloc[0]["name"] == "Alpha"


def test_json_read_preserves_iso_date_strings(tmp_path: Path):
    frames = {
        "reviews": pd.DataFrame([{"id": "REV-1", "date": "2026-06-18"}]),
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))

    back = read_json_dir(str(out))

    assert back["reviews"].iloc[0]["date"] == "2026-06-18"


def test_write_json_dir_date_column_writes_exact_date_envelope(tmp_path: Path) -> None:
    frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "day": pd.Timestamp("2026-08-09").date()}]
        )
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))

    raw = json.loads((out / "events.json").read_text(encoding="utf-8"))
    assert raw == [{"id": "E1", "day": {"$date": "2026-08-09"}}]


def test_write_json_dir_naive_datetime_writes_exact_datetime_envelope(
    tmp_path: Path,
) -> None:
    frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "at": datetime.datetime(2026, 8, 9, 10, 30, 0)}]
        )
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))

    raw = json.loads((out / "events.json").read_text(encoding="utf-8"))
    assert raw == [{"id": "E1", "at": {"$datetime": "2026-08-09T10:30:00"}}]


def test_write_json_dir_aware_datetime_writes_with_offset(tmp_path: Path) -> None:
    tz = datetime.timezone(datetime.timedelta(hours=2))
    frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "at": datetime.datetime(2026, 8, 9, 10, 30, 0, tzinfo=tz)}]
        )
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))

    raw = json.loads((out / "events.json").read_text(encoding="utf-8"))
    assert raw == [{"id": "E1", "at": {"$datetime": "2026-08-09T10:30:00+02:00"}}]


def test_write_json_dir_naive_timestamp_writes_exact_datetime_envelope(
    tmp_path: Path,
) -> None:
    frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "at": pd.Timestamp("2026-08-09T10:30:00")}]
        )
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))

    raw = json.loads((out / "events.json").read_text(encoding="utf-8"))
    assert raw == [{"id": "E1", "at": {"$datetime": "2026-08-09T10:30:00"}}]


def test_write_json_dir_aware_timestamp_writes_with_offset(tmp_path: Path) -> None:
    frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "at": pd.Timestamp("2026-08-09T10:30:00+02:00")}]
        )
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))

    raw = json.loads((out / "events.json").read_text(encoding="utf-8"))
    assert raw == [{"id": "E1", "at": {"$datetime": "2026-08-09T10:30:00+02:00"}}]


def test_write_json_dir_midnight_timestamp_remains_datetime(tmp_path: Path) -> None:
    """A midnight `Timestamp` still writes as `$datetime`, never `$date` --
    no time-of-day heuristic is used (consistent with D-T1's own
    no-heuristic classification decision)."""
    frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "at": pd.Timestamp("2026-08-09T00:00:00")}]
        )
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))

    raw = json.loads((out / "events.json").read_text(encoding="utf-8"))
    assert raw == [{"id": "E1", "at": {"$datetime": "2026-08-09T00:00:00"}}]


def test_write_json_dir_nanosecond_timestamp_emits_max_six_fractional_digits(
    tmp_path: Path,
) -> None:
    frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "at": pd.Timestamp("2026-08-09T10:30:00.123456789")}]
        )
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))

    raw = json.loads((out / "events.json").read_text(encoding="utf-8"))
    assert raw == [{"id": "E1", "at": {"$datetime": "2026-08-09T10:30:00.123456"}}]


def test_write_json_dir_timestamp_with_nat_writes_empty_string_never_nat_literal(
    tmp_path: Path,
) -> None:
    """A `Timestamp`-backed column containing one `pandas.NaT` entry no
    longer raises `TypeError`; the missing entry writes as `""`, matching
    every other column's existing Missing convention, and `{"$datetime":
    "NaT"}` never appears (DT2-DESIGN-REVIEW-F1 / -F6)."""
    frames = {
        "events": pd.DataFrame(
            [
                {"id": "E1", "at": pd.Timestamp("2026-08-09T10:30:00")},
                {"id": "E2", "at": pd.NaT},
                {"id": "E3", "at": pd.Timestamp("2026-08-10T11:00:00")},
            ]
        )
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))

    raw_text = (out / "events.json").read_text(encoding="utf-8")
    assert '"NaT"' not in raw_text
    assert '{"$datetime": "NaT"}' not in raw_text

    raw = json.loads(raw_text)
    assert raw[1] == {"id": "E2", "at": ""}


def test_json_temporal_codec_roundtrips_date() -> None:
    value = pd.Timestamp("2026-08-09").date()
    encoded = json.dumps(value, default=_json_temporal_default)
    decoded = json.loads(encoded, object_hook=_json_temporal_object_hook)
    assert decoded == value
    assert type(decoded) is datetime.date


def test_json_temporal_codec_roundtrips_naive_datetime() -> None:
    value = datetime.datetime(2026, 8, 9, 10, 30, 0, 123456)
    encoded = json.dumps(value, default=_json_temporal_default)
    decoded = json.loads(encoded, object_hook=_json_temporal_object_hook)
    assert decoded == value
    assert decoded.tzinfo is None


def test_json_temporal_codec_roundtrips_aware_datetime() -> None:
    tz = datetime.timezone(datetime.timedelta(hours=-5))
    value = datetime.datetime(2026, 8, 9, 10, 30, 0, tzinfo=tz)
    encoded = json.dumps(value, default=_json_temporal_default)
    decoded = json.loads(encoded, object_hook=_json_temporal_object_hook)
    assert decoded == value
    assert decoded.utcoffset() == value.utcoffset()


def test_json_temporal_codec_does_not_preserve_timestamp_carrier_identity() -> None:
    """Carrier identity (`pandas.Timestamp` vs plain `datetime.datetime`) is
    deliberately not preserved -- decode always yields native
    `datetime.datetime`, never reconstructs a `Timestamp` (27.4)."""
    value = pd.Timestamp("2026-08-09T10:30:00")
    encoded = json.dumps(value, default=_json_temporal_default)
    decoded = json.loads(encoded, object_hook=_json_temporal_object_hook)
    assert decoded == value.to_pydatetime()
    assert type(decoded) is datetime.datetime
    assert not isinstance(decoded, pd.Timestamp)


@pytest.mark.parametrize(
    "payload",
    [
        '{"$date": "not-a-date"}',
        '{"$datetime": "not-a-datetime"}',
        '{"$datetime": 123}',
    ],
)
def test_json_temporal_object_hook_raises_value_error_for_malformed_envelope(
    payload: str,
) -> None:
    with pytest.raises(ValueError):
        json.loads(payload, object_hook=_json_temporal_object_hook)


def test_json_temporal_object_hook_passes_through_ordinary_nested_dict() -> None:
    payload = '{"a": 1, "b": {"nested": true, "c": "x"}}'
    decoded = json.loads(payload, object_hook=_json_temporal_object_hook)
    assert decoded == {"a": 1, "b": {"nested": True, "c": "x"}}


def test_read_json_dir_dtype_str_behavior_unchanged_by_temporal_encoder(
    tmp_path: Path,
) -> None:
    """Option B non-regression: `read_json_dir`'s existing `dtype=str`
    contract is unaffected by the new write-side temporal encoder -- a
    `$datetime` envelope written by `write_json_dir` reads back through the
    unmodified `read_multi` as an unparseable, stringified value, not a
    native `datetime.datetime` (27.11's explicitly-stated boundary)."""
    frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "at": pd.Timestamp("2026-08-09T10:30:00")}]
        )
    }
    out = tmp_path / "data"
    write_json_dir(frames, str(out))

    back = read_json_dir(str(out))
    value = back["events"].iloc[0]["at"]
    assert isinstance(value, str)
    assert value != "2026-08-09T10:30:00"  # not decoded to a native value
