import pandas as pd
from spreadsheet_handling.core.indexing import has_level0, level0_series


def test_level0_series_with_multiindex_single_A():
    df = pd.DataFrame(
        {
            ("A", ""): [1, 2, 3],
            ("B", ""): [10, 20, 30],
        }
    )
    df.columns = pd.MultiIndex.from_tuples(df.columns)

    assert has_level0(df, "A")
    sA = level0_series(df, "A")
    assert list(sA) == [1, 2, 3]


def test_level0_series_missing_raises_keyerror():
    df = pd.DataFrame({"X": [1, 2]})
    try:
        level0_series(df, "A")
        assert False, "expected KeyError"
    except KeyError:
        pass
