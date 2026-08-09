from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.core.flatten import flatten_json
from spreadsheet_handling.core.df_build import build_df_from_records
from spreadsheet_handling.core.unflatten import df_to_objects
from spreadsheet_handling.io_backends.csv_backend import CSVBackend, load_csv_dir

pytestmark = pytest.mark.ftr("FTR-MINIMAL-INTERNAL-VALUE-MODEL-P4A")


def normalize(o):
    if isinstance(o, dict):
        return {k: normalize(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [normalize(x) for x in o]
    return o


def test_csv_roundtrip_unicode_and_multirow(tmp_path: Path):
    samples = [
        {
            "kunde": {
                "name": "Rexi 🦖",
                "adresse": {"straße": "T-Rex-Weg", "stadt": "Dinohausen"},
            },
            "bestellung": {"id": "ORD-001", "datum": "2025-08-31"},
        },
        {
            "kunde": {
                "name": "Galli",
                "adresse": {"straße": "Windgasse", "stadt": "Pelagia"},
            },
            "bestellung": {"id": "ORD-002", "datum": "2025-09-01"},
        },
    ]
    records = [flatten_json(s) for s in samples]
    df = build_df_from_records(records, levels=3)

    csv_path = tmp_path / "tmp.csv"
    CSVBackend().write(df, str(csv_path))
    df_back = CSVBackend().read(str(csv_path), header_levels=3)

    out = [normalize(x) for x in df_to_objects(df_back)]
    assert out == [normalize(s) for s in samples]


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    lines = [",".join(header)] + [",".join(row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_csv_dir_blank_cell_reads_as_empty_string_not_nan(tmp_path: Path):
    """`load_csv_dir` (the `csv_dir` directory-read path) must match the
    already-converged JSON/YAML/single-file-CSV ingress contract: a blank
    cell becomes `""`, never a real pandas NaN carrier.

    FTR-MINIMAL-INTERNAL-VALUE-MODEL-P4A slice D2: before this fix,
    `read_multi` called `pd.read_csv` with no `dtype=str` and no
    `keep_default_na=False`/`na_values=[]`, so ordinary pandas NaN inference
    applied -- the confirmed ingress-side gap behind
    `BUG-ODS-MISSING-CARRIER-LITERAL-NAN-RENDERING-P4A`'s reproduction 2.
    """
    in_dir = tmp_path / "csv_in"
    in_dir.mkdir()
    _write_csv(in_dir / "notes.csv", ["id", "note"], [["1", ""], ["2", "hello"]])

    frames = load_csv_dir(str(in_dir), header_levels=1)
    df = frames["notes"]

    note_col = df[("note",)] if isinstance(df.columns, pd.MultiIndex) else df["note"]
    assert note_col.iloc[0] == "", "blank csv_dir cell must load as an empty string"
    assert not pd.isna(note_col.iloc[0]) or note_col.iloc[0] == "", (
        "blank csv_dir cell must not be a real pandas NaN carrier"
    )
    assert isinstance(note_col.iloc[0], str), "blank cell must be a str, not a float NaN"
    assert note_col.iloc[1] == "hello"


def test_load_csv_dir_numeric_looking_column_is_not_dtype_promoted(tmp_path: Path):
    """A numeric-looking `csv_dir` column must stay string-typed, matching
    the accepted visible-cell string-substrate contract -- not silently
    promoted to `int64`/`float64` by pandas' default dtype inference, which
    would lose a value like a leading-zero code (`"007"`).
    """
    in_dir = tmp_path / "csv_in"
    in_dir.mkdir()
    _write_csv(in_dir / "items.csv", ["id", "code"], [["1", "007"], ["2", "042"]])

    frames = load_csv_dir(str(in_dir), header_levels=1)
    df = frames["items"]

    code_col = df[("code",)] if isinstance(df.columns, pd.MultiIndex) else df["code"]
    assert code_col.tolist() == ["007", "042"], (
        "numeric-looking csv_dir values must survive as exact strings, not be "
        "promoted to int/float and lose leading zeros"
    )
