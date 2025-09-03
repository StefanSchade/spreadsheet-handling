from spreadsheet_handling.core.flatten import flatten_json
from spreadsheet_handling.core.df_build import build_df_from_records


def test_first_seen_order_for_columns():
    sample = {"a": {"b": {"c": 1}}, "x": {"y": 2}, "m": 3}
    df = build_df_from_records([flatten_json(sample)], levels=3)
    # Prüfe, dass die sichtbare Reihenfolge den first-seen Pfaden entspricht
    paths = [".".join([p for p in tup if p]) for tup in df.columns]
    assert paths == ["a.b.c", "x.y", "m"]
