"""R1: reference/graph finding reports emit a Scalar-safe row_index.

FTR-TRUSTED-INGRESS-P4A section 10 ("Validation finding-frame decision",
Option R1) requires ``validate_references`` and ``validate_graph`` warn/report
producers to publish ``row_index`` as an ordinary Scalar-compatible value. A
``pandas.MultiIndex`` row index arrives at ``ReferenceFinding.row_index`` as a
plain Python ``tuple`` from ``DataFrame.iterrows()`` -- not itself Scalar --
so it must be projected to a stable String rather than passed through raw.
An already Scalar row index (the maintained default-index case) is preserved
unchanged.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.validations.graph_validations import validate_graph
from spreadsheet_handling.domain.validations.reference_validations import validate_references

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _multiindex_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "region": ["east", "east", "west"],
            "period": [1, 1, 2],
            "id": ["p1", "p1", "p2"],
        }
    )
    return frame.set_index(["region", "period"])


def test_validate_references_scalarizes_multiindex_row_index() -> None:
    frames = {"items": _multiindex_frame()}
    out = validate_references(
        frames,
        rules=[{"type": "unique", "frame": "items", "columns": ["id"]}],
        mode="warn",
    )
    findings = out["validation_findings"]

    assert not findings.empty
    row_indexes = findings["row_index"].tolist()
    assert row_indexes == ["east, 1", "east, 1"]
    assert all(type(value) is str for value in row_indexes)


def test_validate_references_preserves_ordinary_scalar_row_index() -> None:
    frames = {
        "items": pd.DataFrame({"id": ["p1", "p1"]}),
    }
    out = validate_references(
        frames,
        rules=[{"type": "unique", "frame": "items", "columns": ["id"]}],
        mode="warn",
    )
    findings = out["validation_findings"]

    # The maintained default-index case is an already-admitted Scalar label
    # and is preserved unchanged, not stringified.
    assert findings["row_index"].tolist() == [0, 1]
    assert all(type(value) is int for value in findings["row_index"].tolist())


def test_validate_graph_scalarizes_multiindex_row_index() -> None:
    edges = _multiindex_frame().rename(columns={"id": "source_id"})
    edges["target_id"] = ["p1", "p1", "p1"]
    nodes = pd.DataFrame({"node_id": ["p1"]})
    frames = {"edges": edges, "nodes": nodes}

    out = validate_graph(
        frames,
        graph="demo_graph",
        nodes=[{"name": "nodes", "frame": "nodes", "key": "node_id"}],
        edges=[
            {
                "name": "edge",
                "frame": "edges",
                "source_node": "nodes",
                "source_columns": ["source_id"],
                "target_node": "nodes",
                "target_columns": ["target_id"],
            }
        ],
        checks=["endpoints_exist"],
        mode="warn",
    )
    findings = out["graph_validation_findings"]

    assert not findings.empty
    row_indexes = findings["row_index"].tolist()
    assert row_indexes == ["west, 2"]
    assert all(type(value) is str for value in row_indexes)
