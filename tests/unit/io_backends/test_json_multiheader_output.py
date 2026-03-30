from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from spreadsheet_handling.domain.transformations.helpers import flatten_headers
from spreadsheet_handling.io_backends.json_backend import write_json_dir


def test_json_backend_writes_nested_objects_for_multiindex_columns(tmp_path: Path) -> None:
    cols = pd.MultiIndex.from_tuples([
        ("order", "id"),
        ("order", "date"),
        ("customer", "name"),
    ])
    frames = {
        "orders": pd.DataFrame(
            [["O1", "2026-01-01", "Alice"], ["O2", "2026-01-02", "Bob"]],
            columns=cols,
        )
    }

    out = tmp_path / "out"
    write_json_dir(str(out), frames)

    data = json.loads((out / "orders.json").read_text(encoding="utf-8"))
    assert data[0]["order"]["id"] == "O1"
    assert data[0]["order"]["date"] == "2026-01-01"
    assert data[0]["customer"]["name"] == "Alice"


def test_flatten_step_keeps_json_output_flat(tmp_path: Path) -> None:
    cols = pd.MultiIndex.from_tuples([
        ("order", "id"),
        ("order", "date"),
        ("customer", "name"),
    ])
    frames = {
        "orders": pd.DataFrame([["O1", "2026-01-01", "Alice"]], columns=cols)
    }

    frames_flat = flatten_headers("orders", mode="join", sep=".")(frames)

    out = tmp_path / "out_flat"
    write_json_dir(str(out), frames_flat)

    data = json.loads((out / "orders.json").read_text(encoding="utf-8"))
    assert "order.id" in data[0]
    assert "order.date" in data[0]
    assert "customer.name" in data[0]
    assert isinstance(data[0]["order.id"], str)
