from __future__ import annotations

import pandas as pd

import pytest

from spreadsheet_handling.domain.transformations.helpers import (
    mark_helpers,
    clean_aux_columns,
    flatten_headers,
    unflatten_headers,
)

pytestmark = pytest.mark.ftr("FTR-MULTIHEADER-P2")


def test_mark_helpers_and_clean() -> None:
    df = pd.DataFrame(
        [
            {"id": "P1", "name": "A", "fk_branch": "B1"},
            {"id": "P2", "name": "B", "fk_branch": "B2"},
        ]
    )
    frames = {"products": df}

    # mark two cols as helper (with custom prefix)
    step_mark = mark_helpers(sheet="products", cols=["fk_branch", "name"], prefix="helper__")
    frames2 = step_mark(frames)

    assert set(frames2["products"].columns) == {"id", "helper__name", "helper__fk_branch"}

    # cleaning should remove those helper columns again
    step_clean = clean_aux_columns(sheet="products", drop_prefixes=("helper__",))
    frames3 = step_clean(frames2)

    assert set(frames3["products"].columns) == {"id"}


def test_flatten_join_then_unflatten_roundtrip_headers() -> None:
    cols = pd.MultiIndex.from_tuples(
        [
            ("order", "id"),
            ("order", "date"),
            ("customer", "name"),
        ]
    )
    df = pd.DataFrame([["O1", "2026-01-01", "Alice"]], columns=cols)
    frames = {"orders": df}

    flat = flatten_headers("orders", mode="join", sep=".")(frames)
    assert list(flat["orders"].columns) == ["order.id", "order.date", "customer.name"]

    restored = unflatten_headers("orders", sep=".")(flat)
    assert isinstance(restored["orders"].columns, pd.MultiIndex)
    assert list(restored["orders"].columns) == list(cols)


def test_unflatten_only_targets_selected_sheet() -> None:
    frames = {
        "orders": pd.DataFrame([["O1"]], columns=["order.id"]),
        "products": pd.DataFrame([["P1"]], columns=["product_id"]),
    }

    out = unflatten_headers("orders", sep=".")(frames)
    assert isinstance(out["orders"].columns, pd.MultiIndex)
    assert not isinstance(out["products"].columns, pd.MultiIndex)


def test_unflatten_requires_non_empty_separator() -> None:
    frames = {"orders": pd.DataFrame([["O1"]], columns=["order.id"])}
    step = unflatten_headers("orders", sep="")

    try:
        _ = step(frames)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "non-empty sep" in str(e)


def test_flatten_join_preserves_empty_levels_roundtrip() -> None:
    """Ragged MultiIndex: empty-string levels must survive flatten→unflatten."""
    cols = pd.MultiIndex.from_tuples(
        [
            ("order", ""),
            ("date", ""),
            ("customer", "name"),
        ]
    )
    df = pd.DataFrame([["O1", "2026-01-01", "Alice"]], columns=cols)
    frames = {"orders": df}

    flat = flatten_headers("orders", mode="join", sep=".")(frames)
    assert list(flat["orders"].columns) == ["order.", "date.", "customer.name"]

    restored = unflatten_headers("orders", sep=".")(flat)
    assert isinstance(restored["orders"].columns, pd.MultiIndex)
    assert list(restored["orders"].columns) == list(cols)
