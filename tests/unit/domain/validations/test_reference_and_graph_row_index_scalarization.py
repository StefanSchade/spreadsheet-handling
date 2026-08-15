"""R1: reference/graph finding reports emit a Scalar-safe row_index.

FTR-TRUSTED-INGRESS-P4A section 10 ("Validation finding-frame decision",
Option R1) requires ``validate_references`` and ``validate_graph`` warn/report
producers to publish ``row_index`` as an ordinary Scalar-compatible value,
*unconditionally* -- not merely for the ``MultiIndex`` case. A
``pandas.MultiIndex`` row index arrives at ``ReferenceFinding.row_index`` as a
plain Python ``tuple`` from ``DataFrame.iterrows()`` -- not itself Scalar --
so it must be projected to a stable String rather than passed through raw.
An already Scalar row index (the maintained default-index case) is preserved
unchanged. Current physical-axis authority imposes no row-index grammar
(section 25 defer matrix), so an arbitrary hashable object index is a
currently reachable state, not a hypothetical one (independent E4
implementation review af2dcc2, Important finding I1) -- also covered here.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.validations.graph_validations import validate_graph
from spreadsheet_handling.domain.validations.reference_validations import validate_references

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


class _Hostile:
    """A hashable object whose formatting protocols must never run."""

    def __repr__(self) -> str:  # pragma: no cover - must never run
        raise AssertionError("repr must not run")

    def __str__(self) -> str:  # pragma: no cover - must never run
        raise AssertionError("str must not run")


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


def test_validate_references_replaces_a_hostile_nonscalar_nontuple_row_index() -> None:
    """I1 reproduction: a non-tuple, non-Scalar hashable object index must
    not reach the report cell raw, and its formatting protocols must never
    be invoked."""
    frame = pd.DataFrame(
        {"id": ["p1", "p1"]}, index=pd.Index([_Hostile(), _Hostile()], dtype=object)
    )
    out = validate_references(
        {"items": frame},
        rules=[{"type": "unique", "frame": "items", "columns": ["id"]}],
        mode="warn",
    )
    findings = out["validation_findings"]

    assert not findings.empty
    row_indexes = findings["row_index"].tolist()
    assert row_indexes == ["<unsupported row index>", "<unsupported row index>"]
    assert all(type(value) is str for value in row_indexes)


def test_validate_graph_replaces_a_hostile_nonscalar_nontuple_row_index() -> None:
    edges = pd.DataFrame(
        {"source_id": ["p2"], "target_id": ["p1"]},
        index=pd.Index([_Hostile()], dtype=object),
    )
    nodes = pd.DataFrame({"node_id": ["p1"]})

    out = validate_graph(
        {"edges": edges, "nodes": nodes},
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
    assert row_indexes == ["<unsupported row index>"]
    assert all(type(value) is str for value in row_indexes)
