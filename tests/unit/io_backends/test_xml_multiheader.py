from __future__ import annotations

import pandas as pd
import pytest
from pathlib import Path
import xml.etree.ElementTree as ET

from spreadsheet_handling.io_backends.xml_backend import XMLBackend
from spreadsheet_handling.domain.transformations.helpers import flatten_headers, unflatten_headers

pytestmark = pytest.mark.ftr("FTR-XML-MULTIHEADER-P2")



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _multiindex_frames() -> dict[str, pd.DataFrame]:
    cols = pd.MultiIndex.from_tuples([
        ("order", "id"),
        ("order", "date"),
        ("customer", "name"),
    ])
    df = pd.DataFrame([
        ["O1", "2026-01-01", "Alice"],
        ["O2", "2026-02-15", "Bob"],
    ], columns=cols)
    return {"orders": df}


def _flat_frames() -> dict[str, pd.DataFrame]:
    df = pd.DataFrame([
        {"product_id": "P1", "name": "Widget", "price": "9.99"},
        {"product_id": "P2", "name": "Gadget", "price": "19.99"},
    ])
    return {"products": df}


# ---------------------------------------------------------------------------
# 1. MultiIndex → nested XML
# ---------------------------------------------------------------------------

class TestMultiIndexToNestedXml:

    def test_write_produces_nested_elements(self, tmp_path: Path) -> None:
        frames = _multiindex_frames()
        XMLBackend().write_multi(frames, str(tmp_path))

        xml_path = tmp_path / "orders.xml"
        assert xml_path.exists()

        tree = ET.parse(xml_path)
        root = tree.getroot()
        assert root.tag == "orders"

        rows = list(root)
        assert len(rows) == 2

        # First row should have nested structure: <order><id>O1</id><date>...</date></order>
        row0 = rows[0]
        order_el = row0.find("order")
        assert order_el is not None
        assert order_el.find("id") is not None
        assert order_el.find("id").text == "O1"
        assert order_el.find("date").text == "2026-01-01"

        customer_el = row0.find("customer")
        assert customer_el is not None
        assert customer_el.find("name").text == "Alice"

    def test_write_read_roundtrip_nested(self, tmp_path: Path) -> None:
        frames = _multiindex_frames()
        backend = XMLBackend()
        backend.write_multi(frames, str(tmp_path))

        loaded = backend.read_multi(str(tmp_path), header_levels=1)
        assert "orders" in loaded

        df = loaded["orders"]
        assert len(df) == 2
        # Read-back uses dotted keys: "order.id", "order.date", "customer.name"
        assert "order.id" in df.columns
        assert "order.date" in df.columns
        assert "customer.name" in df.columns
        assert list(df["order.id"]) == ["O1", "O2"]


# ---------------------------------------------------------------------------
# 2. MultiIndex → flatten → flat XML
# ---------------------------------------------------------------------------

class TestFlattenThenXml:

    def test_flatten_then_write_produces_flat_elements(self, tmp_path: Path) -> None:
        frames = _multiindex_frames()
        flat_frames = flatten_headers("orders", mode="join", sep=".")(frames)
        XMLBackend().write_multi(flat_frames, str(tmp_path))

        tree = ET.parse(tmp_path / "orders.xml")
        root = tree.getroot()
        rows = list(root)
        row0 = rows[0]

        # Flat columns become direct child elements (dots replaced with underscores in tag)
        tags = [child.tag for child in row0]
        assert "order_id" in tags
        assert "order_date" in tags
        assert "customer_name" in tags


# ---------------------------------------------------------------------------
# 3. XML → frames → unflatten round-trip
# ---------------------------------------------------------------------------

class TestXmlToUnflattenRoundtrip:

    def test_read_then_unflatten_rebuilds_multiindex(self, tmp_path: Path) -> None:
        """Write MultiIndex as nested XML, read back, then unflatten to get MultiIndex."""
        frames = _multiindex_frames()
        backend = XMLBackend()
        backend.write_multi(frames, str(tmp_path))

        loaded = backend.read_multi(str(tmp_path), header_levels=1)
        # Columns are dotted: "order.id", "order.date", "customer.name"
        restored = unflatten_headers("orders", sep=".")(loaded)

        df = restored["orders"]
        assert isinstance(df.columns, pd.MultiIndex)
        assert df.columns.nlevels == 2
        assert ("order", "id") in df.columns
        assert ("order", "date") in df.columns
        assert ("customer", "name") in df.columns
        assert list(df[("order", "id")]) == ["O1", "O2"]

    def test_flat_xml_write_read_roundtrip(self, tmp_path: Path) -> None:
        """Flat frames → XML → read back → values match."""
        frames = _flat_frames()
        backend = XMLBackend()
        backend.write_multi(frames, str(tmp_path))

        loaded = backend.read_multi(str(tmp_path), header_levels=1)
        df = loaded["products"]
        assert len(df) == 2
        assert list(df["product_id"]) == ["P1", "P2"]
        assert list(df["name"]) == ["Widget", "Gadget"]
        assert list(df["price"]) == ["9.99", "19.99"]


# ---------------------------------------------------------------------------
# 4. Edge cases
# ---------------------------------------------------------------------------

class TestXmlEdgeCases:

    def test_empty_dataframe(self, tmp_path: Path) -> None:
        frames = {"empty": pd.DataFrame()}
        backend = XMLBackend()
        backend.write_multi(frames, str(tmp_path))

        loaded = backend.read_multi(str(tmp_path), header_levels=1)
        assert "empty" in loaded
        assert loaded["empty"].empty

    def test_helper_columns_skipped_on_write(self, tmp_path: Path) -> None:
        cols = pd.MultiIndex.from_tuples([
            ("order", "id"),
            ("_helper", "flag"),
        ])
        df = pd.DataFrame([["O1", "x"]], columns=cols)
        XMLBackend().write_multi({"orders": df}, str(tmp_path))

        tree = ET.parse(tmp_path / "orders.xml")
        root = tree.getroot()
        row0 = list(root)[0]
        # _helper should not appear
        tags = [child.tag for child in row0]
        assert "_helper" not in tags
        assert "order" in tags

    def test_ragged_multiindex(self, tmp_path: Path) -> None:
        """Ragged MultiIndex: some columns have empty 2nd level."""
        cols = pd.MultiIndex.from_tuples([
            ("id", ""),
            ("order", "date"),
        ])
        df = pd.DataFrame([["O1", "2026-01-01"]], columns=cols)
        backend = XMLBackend()
        backend.write_multi({"data": df}, str(tmp_path))

        tree = ET.parse(tmp_path / "data.xml")
        root = tree.getroot()
        row0 = list(root)[0]
        # "id" with empty 2nd level → direct <id> element
        id_el = row0.find("id")
        assert id_el is not None
        assert id_el.text == "O1"
        # "order.date" → nested <order><date>
        order_el = row0.find("order")
        assert order_el is not None
        assert order_el.find("date").text == "2026-01-01"
