import json
import tempfile
from pathlib import Path

from spreadsheet_handling.core.flatten import flatten_json
from spreadsheet_handling.core.df_build import build_df_from_records
from spreadsheet_handling.core.unflatten import df_to_objects
from spreadsheet_handling.io_backends.excel_xlsxwriter import ExcelBackend

def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))

def normalize(obj):
    # ignore helper keys starting with "_", and order
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [normalize(x) for x in obj]
    return obj

def test_roundtrip_from_file(tmp_path: Path):
    sample_path = Path(__file__).parent / "data" / "test_roundtrip.json"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))

    records = [flatten_json(sample)]
    df = build_df_from_records(records, levels=3)

    xlsx = tmp_path / "tmp.xlsx"
    ExcelBackend().write(df, str(xlsx), sheet_name="Daten")

    df_back = ExcelBackend().read(str(xlsx), header_levels=3, sheet_name="Daten")
    objs = df_to_objects(df_back)

    assert len(objs) == 1
    assert normalize(objs[0]) == normalize(sample)

def test_roundtrip_basic(tmp_path: Path):
    sample = {
        "kunde": {
            "name": "Rexi",
            "adresse": {"strasse": "T-Rex-Weg", "stadt": "Dinohausen"}
        },
        "bestellung": {"id": "ORD-001", "datum": "2025-08-31"}
    }
    records = [flatten_json(sample)]
    df = build_df_from_records(records, levels=3)

    excel = tmp_path / "tmp.xlsx"
    ExcelBackend().write(df, str(excel), sheet_name="Daten")

    df_back = ExcelBackend().read(str(excel), header_levels=3, sheet_name="Daten")
    objs = df_to_objects(df_back)
    assert len(objs) == 1
    assert normalize(objs[0]) == normalize(sample)

def test_order_stability():
    sample = {"a": {"b": {"c": 1}}, "x": {"y": 2}, "m": 3}
    records = [flatten_json(sample)]
    df = build_df_from_records(records, levels=3)
    # first-seen order is preserved in df.columns
    cols = [".".join([s for s in tup if s]) for tup in df.columns]
    assert cols[:3] == ["a.b.c", "x.y", "m"]  # adjust if your implementation differs

