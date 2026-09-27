from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from spreadsheet_handling.domain.validations.reference_validations import FINDING_COLUMNS
from spreadsheet_handling.domain.validations.graph_validations import validate_graph

pytestmark = pytest.mark.ftr("FTR-GRAPH-REFERENCE-VALIDATIONS-P4A")


def _operation_graph_rules() -> dict:
    return {
        "graph": "calculation_operation_network",
        "nodes": [
            {"name": "operations", "frame": "calculation_operations", "key": "operation_id"},
            {"name": "variables", "frame": "variables", "key": "variable_id"},
        ],
        "edges": [
            {
                "name": "operation_outputs",
                "frame": "operation_outputs",
                "source_node": "operations",
                "source_column": "operation_id",
                "target_node": "variables",
                "target_column": "variable_id",
                "unique": True,
            }
        ],
    }


def test_validate_graph_reports_missing_edge_endpoints() -> None:
    frames = {
        "calculation_operations": pd.DataFrame([{"operation_id": "op1"}]),
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "operation_outputs": pd.DataFrame(
            [
                {"operation_id": "op1", "variable_id": "v1"},
                {"operation_id": "missing_op", "variable_id": "v1"},
                {"operation_id": "op1", "variable_id": "missing_var"},
            ]
        ),
    }

    out = validate_graph(frames, **_operation_graph_rules())

    assert list(out["graph_validation_findings"].columns) == FINDING_COLUMNS
    assert out["graph_validation_findings"].to_dict(orient="records") == [
        {
            "rule_type": "graph_endpoint",
            "frame": "operation_outputs",
            "columns": "operation_id",
            "row_index": 1,
            "value": "missing_op",
            "target_frame": "calculation_operations",
            "target_columns": "operation_id",
            "severity": "warn",
            "message": (
                "Graph 'calculation_operation_network' edge 'operation_outputs' "
                "has unresolved source endpoint for node 'operations'."
            ),
        },
        {
            "rule_type": "graph_endpoint",
            "frame": "operation_outputs",
            "columns": "variable_id",
            "row_index": 2,
            "value": "missing_var",
            "target_frame": "variables",
            "target_columns": "variable_id",
            "severity": "warn",
            "message": (
                "Graph 'calculation_operation_network' edge 'operation_outputs' "
                "has unresolved target endpoint for node 'variables'."
            ),
        },
    ]


def test_validate_graph_reports_duplicate_edges_when_unique_is_enabled() -> None:
    frames = {
        "calculation_operations": pd.DataFrame([{"operation_id": "op1"}]),
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "operation_outputs": pd.DataFrame(
            [
                {"operation_id": "op1", "variable_id": "v1"},
                {"operation_id": "op1", "variable_id": "v1"},
            ]
        ),
    }

    out = validate_graph(frames, **_operation_graph_rules())

    assert out["graph_validation_findings"].loc[:, ["rule_type", "row_index", "value"]].to_dict(
        orient="records"
    ) == [
        {"rule_type": "graph_unique_edge", "row_index": 0, "value": '["op1", "v1"]'},
        {"rule_type": "graph_unique_edge", "row_index": 1, "value": '["op1", "v1"]'},
    ]


def test_validate_graph_supports_composite_edge_keys() -> None:
    frames = {
        "operation_slots": pd.DataFrame(
            [
                {"operation_id": "op1", "slot_id": "main"},
                {"operation_id": "op1", "slot_id": "secondary"},
            ]
        ),
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "slot_outputs": pd.DataFrame(
            [
                {"operation_id": "op1", "slot_id": "main", "variable_id": "v1"},
                {"operation_id": "op1", "slot_id": "missing", "variable_id": "v1"},
                {"operation_id": "op1", "slot_id": "main", "variable_id": "v1"},
            ]
        ),
    }

    out = validate_graph(
        frames,
        graph="slot_network",
        nodes=[
            {
                "name": "operation_slots",
                "frame": "operation_slots",
                "key": ["operation_id", "slot_id"],
            },
            {"name": "variables", "frame": "variables", "key": "variable_id"},
        ],
        edges=[
            {
                "name": "slot_outputs",
                "frame": "slot_outputs",
                "source_node": "operation_slots",
                "source_columns": ["operation_id", "slot_id"],
                "target_node": "variables",
                "target_column": "variable_id",
                "unique": True,
            }
        ],
    )

    assert out["graph_validation_findings"].loc[:, ["rule_type", "row_index", "value"]].to_dict(
        orient="records"
    ) == [
        {"rule_type": "graph_endpoint", "row_index": 1, "value": '["op1", "missing"]'},
        {"rule_type": "graph_unique_edge", "row_index": 0, "value": '["op1", "main", "v1"]'},
        {"rule_type": "graph_unique_edge", "row_index": 2, "value": '["op1", "main", "v1"]'},
    ]


def test_validate_graph_fail_mode_raises_with_row_context() -> None:
    frames = {
        "calculation_operations": pd.DataFrame([{"operation_id": "op1"}]),
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "operation_outputs": pd.DataFrame([{"operation_id": "missing_op", "variable_id": "v1"}]),
    }

    with pytest.raises(ValueError, match="operation_outputs\\(operation_id\\).*missing_op"):
        validate_graph(frames, mode="fail", **_operation_graph_rules())


def test_validate_graph_can_run_selected_checks_only() -> None:
    frames = {
        "calculation_operations": pd.DataFrame([{"operation_id": "op1"}]),
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "operation_outputs": pd.DataFrame(
            [
                {"operation_id": "op1", "variable_id": "v1"},
                {"operation_id": "op1", "variable_id": "v1"},
            ]
        ),
    }

    out = validate_graph(frames, checks=["endpoints_exist"], **_operation_graph_rules())

    assert out["graph_validation_findings"].empty


def test_graph_endpoints_use_category_aware_relation_identity() -> None:
    frames = {
        "source_nodes": pd.DataFrame({"key": pd.Series([1], dtype="object")}),
        "target_nodes": pd.DataFrame({"key": pd.Series([1], dtype="object")}),
        "edges": pd.DataFrame(
            {
                "source_key": pd.Series([1.0, "1", True], dtype="object"),
                "target_key": pd.Series([1, 1, 1], dtype="object"),
            }
        ),
    }

    out = validate_graph(
        frames,
        graph="category_aware_network",
        nodes=[
            {"name": "source", "frame": "source_nodes", "key": "key"},
            {"name": "target", "frame": "target_nodes", "key": "key"},
        ],
        edges=[
            {
                "name": "links",
                "frame": "edges",
                "source_node": "source",
                "source_column": "source_key",
                "target_node": "target",
                "target_column": "target_key",
            }
        ],
        checks=["endpoints_exist"],
    )

    assert out["graph_validation_findings"].loc[:, ["row_index", "value"]].to_dict(orient="records") == [
        {"row_index": 1, "value": "1"},
        {"row_index": 2, "value": "True"},
    ]


def test_graph_endpoints_preserve_object_datetime64_picosecond_precision() -> None:
    frames = {
        "nodes": pd.DataFrame({"key": pd.Series([np.datetime64(1, "ps")], dtype="object")}),
        "edges": pd.DataFrame({"key": pd.Series([np.datetime64(2, "ps")], dtype="object")}),
    }

    out = validate_graph(
        frames,
        graph="picosecond_network",
        nodes=[{"name": "nodes", "frame": "nodes", "key": "key"}],
        edges=[
            {
                "name": "links",
                "frame": "edges",
                "source_node": "nodes",
                "source_column": "key",
                "target_node": "nodes",
                "target_column": "key",
            }
        ],
        checks=["endpoints_exist"],
    )

    assert out["graph_validation_findings"].loc[:, ["row_index", "columns"]].to_dict(
        orient="records"
    ) == [
        {"row_index": 0, "columns": "key"},
        {"row_index": 0, "columns": "key"},
    ]


def test_default_unique_edge_columns_retain_blank_tuple_identity() -> None:
    frames = {
        "nodes": pd.DataFrame([{"key": "node"}]),
        "edges": pd.DataFrame(
            [
                {"source_key": "", "target_key": "node"},
                {"source_key": "", "target_key": "node"},
            ]
        ),
    }

    out = validate_graph(
        frames,
        graph="default_columns_diverge",
        nodes=[{"name": "nodes", "frame": "nodes", "key": "key"}],
        edges=[
            {
                "name": "links",
                "frame": "edges",
                "source_node": "nodes",
                "source_column": "source_key",
                "target_node": "nodes",
                "target_column": "target_key",
                "unique": True,
            }
        ],
    )

    # Default unique_columns are endpoint columns, but only endpoint resolution
    # excludes Missing values; generic edge tuples still count blank components.
    assert out["graph_validation_findings"].loc[:, ["rule_type", "row_index"]].to_dict(orient="records") == [
        {"rule_type": "graph_endpoint", "row_index": 0},
        {"rule_type": "graph_endpoint", "row_index": 1},
        {"rule_type": "graph_unique_edge", "row_index": 0},
        {"rule_type": "graph_unique_edge", "row_index": 1},
    ]
