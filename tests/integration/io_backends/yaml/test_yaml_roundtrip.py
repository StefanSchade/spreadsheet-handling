"""YAML backend integration slice.

Verifies the real YAML directory writer and reader preserve visible tabular
frames, including an empty frame, through a filesystem roundtrip.

Also covers `FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` D-T2.1's accepted
structured-persistence contract (section 27.6/27.13): `save_yaml_dir` gains
a persistence-local `_yaml_safe_temporal` conversion (`pandas.NaT` checked
before `pandas.Timestamp` before everything else) so a `Timestamp`-typed
column -- naive, timezone-aware, or containing `pandas.NaT` -- no longer
crashes with `yaml.representer.RepresenterError`; `load_yaml_dir`'s read
side is unaffected (YAML's native `date`/`timestamp` tags already round-trip
correctly).
"""

from __future__ import annotations

import warnings
import zoneinfo
from pathlib import Path
from typing import Dict

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.io_backends.yaml_backend import (
    load_yaml_dir,
    save_yaml_dir,
)

Frames = Dict[str, pd.DataFrame]

pytestmark = pytest.mark.ftr("FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A")


def test_yaml_roundtrip(tmp_path: Path) -> None:
    frames: Frames = {
        "products": pd.DataFrame([{"id": "P1", "name": "A"}, {"id": "P2", "name": "B"}]),
        "branches": pd.DataFrame([{"branch_id": "B1", "city": "X"}]),
        "empty": pd.DataFrame([]),
    }

    out = tmp_path / "data"
    save_yaml_dir(frames, str(out))

    loaded = load_yaml_dir(str(out))
    assert set(loaded.keys()) == set(frames.keys())

    for k in frames.keys():
        a = frames[k].fillna("").sort_index(axis=1)
        b = loaded[k].fillna("").sort_index(axis=1)
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


def test_pure_date_roundtrip_unaffected_by_temporal_helper(tmp_path: Path) -> None:
    """Non-regression: a plain `datetime.date` column round-trips exactly,
    unaffected by `_yaml_safe_temporal`'s existence (27.1/27.6)."""
    frames: Frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "day": pd.Timestamp("2026-08-09").date()}]
        )
    }
    out = tmp_path / "data"
    save_yaml_dir(frames, str(out))

    raw = (out / "events.yml").read_text(encoding="utf-8")
    assert "2026-08-09" in raw
    assert "'" not in raw and '"' not in raw  # native, unquoted YAML date scalar

    loaded = load_yaml_dir(str(out))
    assert loaded["events"].iloc[0]["day"] == pd.Timestamp("2026-08-09").date()


def test_naive_timestamp_write_succeeds(tmp_path: Path) -> None:
    """A naive `pandas.Timestamp` column no longer raises
    `RepresenterError` on `save_yaml_dir` (DT2-DESIGN-REVIEW discovery)."""
    frames: Frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "at": pd.Timestamp("2026-08-09T10:30:00")}]
        )
    }
    out = tmp_path / "data"
    save_yaml_dir(frames, str(out))

    loaded = load_yaml_dir(str(out))
    value = loaded["events"].iloc[0]["at"]
    assert value == pd.Timestamp("2026-08-09T10:30:00").to_pydatetime()
    assert value.tzinfo is None


def test_aware_timestamp_write_succeeds(tmp_path: Path) -> None:
    """A timezone-aware `pandas.Timestamp` column (mixed offsets) no longer
    raises `RepresenterError` on `save_yaml_dir`."""
    frames: Frames = {
        "events": pd.DataFrame(
            [
                {"id": "E1", "at": pd.Timestamp("2026-08-09T10:30:00+02:00")},
                {"id": "E2", "at": pd.Timestamp("2026-08-09T10:30:00+05:00")},
            ]
        )
    }
    out = tmp_path / "data"
    save_yaml_dir(frames, str(out))

    loaded = load_yaml_dir(str(out))
    first = loaded["events"].iloc[0]["at"]
    second = loaded["events"].iloc[1]["at"]
    assert first.utcoffset().total_seconds() == 2 * 3600
    assert second.utcoffset().total_seconds() == 5 * 3600


def test_timestamp_with_nat_write_succeeds_and_nat_persists_as_null(
    tmp_path: Path,
) -> None:
    """A `Timestamp`-backed column containing one `pandas.NaT` entry no
    longer raises `RepresenterError`; the written YAML represents that entry
    as `null`, matching a `datetime.date` column's own existing Missing
    representation (DT2-DESIGN-REVIEW-F1 / -F6)."""
    frames: Frames = {
        "events": pd.DataFrame(
            [
                {"id": "E1", "at": pd.Timestamp("2026-08-09T10:30:00")},
                {"id": "E2", "at": pd.NaT},
                {"id": "E3", "at": pd.Timestamp("2026-08-10T11:00:00")},
            ]
        )
    }
    out = tmp_path / "data"
    save_yaml_dir(frames, str(out))

    raw = (out / "events.yml").read_text(encoding="utf-8")
    assert "at: null" in raw

    loaded = load_yaml_dir(str(out))
    # Reloaded as a real DataFrame, pandas promotes the column to
    # datetime64-dtype (two real Timestamps + one None) and represents the
    # missing entry as pandas.NaT -- the temporal column's own Missing
    # carrier, not the bare None a mixed-type/object column would keep.
    assert pd.isna(loaded["events"].iloc[1]["at"])


def test_load_then_unmodified_resave_of_timestamp_and_blank_succeeds(
    tmp_path: Path,
) -> None:
    """Realistic scenario, D-T2's own headline motivation: load a YAML file
    with a timestamp column and one blank cell via `load_yaml_dir`, change
    nothing, and `save_yaml_dir` it back -- no longer crashes."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "events.yml").write_text(
        "- id: E1\n  at: 2026-08-09 10:30:00\n"
        "- id: E2\n  at:\n",
        encoding="utf-8",
    )

    loaded = load_yaml_dir(str(src))
    assert loaded["events"]["at"].dtype.kind == "M"  # datetime64
    assert pd.isna(loaded["events"].iloc[1]["at"])

    out = tmp_path / "out"
    save_yaml_dir(loaded, str(out))

    reloaded = load_yaml_dir(str(out))
    assert reloaded["events"].iloc[0]["at"] == pd.Timestamp("2026-08-09T10:30:00").to_pydatetime()
    assert pd.isna(reloaded["events"].iloc[1]["at"])


def test_nanosecond_timestamp_writes_at_microsecond_precision_no_warning(
    tmp_path: Path,
) -> None:
    """A nanosecond-precision `Timestamp` writes without emitting
    `UserWarning` (27.1's "Discarding nonzero nanoseconds" finding), and
    truncates to exactly microsecond precision."""
    frames: Frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "at": pd.Timestamp("2026-08-09T10:30:00.123456789")}]
        )
    }
    out = tmp_path / "data"

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        save_yaml_dir(frames, str(out))

    loaded = load_yaml_dir(str(out))
    value = loaded["events"].iloc[0]["at"]
    assert value.microsecond == 123456
    assert value == pd.Timestamp("2026-08-09T10:30:00.123456").to_pydatetime()


def test_named_zone_input_preserves_offset_not_necessarily_zoneinfo_identity(
    tmp_path: Path,
) -> None:
    """A `ZoneInfo`-tagged `Timestamp` survives with its exact numeric offset
    (DST-correct across two different periods), but decode is not required
    to reconstruct a `ZoneInfo`-backed timezone (27.4, DT2-DESIGN-REVIEW-F4)."""
    berlin = zoneinfo.ZoneInfo("Europe/Berlin")
    frames: Frames = {
        "events": pd.DataFrame(
            [
                {"id": "summer", "at": pd.Timestamp("2026-08-09T10:30:00", tz=berlin)},
                {"id": "winter", "at": pd.Timestamp("2026-12-09T10:30:00", tz=berlin)},
            ]
        )
    }
    out = tmp_path / "data"
    save_yaml_dir(frames, str(out))

    loaded = load_yaml_dir(str(out))
    summer = loaded["events"].iloc[0]["at"]
    winter = loaded["events"].iloc[1]["at"]
    assert summer.utcoffset().total_seconds() == 2 * 3600  # CEST
    assert winter.utcoffset().total_seconds() == 1 * 3600  # CET
    # Awareness and offset are preserved; exact zone identity is not.
    assert not isinstance(summer.tzinfo, zoneinfo.ZoneInfo)
    assert not isinstance(winter.tzinfo, zoneinfo.ZoneInfo)


def test_save_yaml_dir_does_not_mutate_global_safe_dumper(tmp_path: Path) -> None:
    """No global `yaml.SafeDumper.add_representer` call is made -- the
    temporal conversion is a value-level mapping, not a representer
    registration (27.6's rejected alternative)."""
    before = dict(yaml.SafeDumper.yaml_representers)

    frames: Frames = {
        "events": pd.DataFrame(
            [{"id": "E1", "at": pd.Timestamp("2026-08-09T10:30:00")}]
        )
    }
    out = tmp_path / "data"
    save_yaml_dir(frames, str(out))

    after = dict(yaml.SafeDumper.yaml_representers)
    assert set(before.keys()) == set(after.keys())
