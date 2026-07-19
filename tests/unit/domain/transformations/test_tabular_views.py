from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.tabular_views import pivot_frame
from spreadsheet_handling.pipeline import build_steps_from_config, run_pipeline

pytestmark = pytest.mark.ftr("FTR-DECLARATIVE-TABULAR-VIEW-OPS-P4A")


def test_pivot_frame_builds_bounded_display_view_with_join_aggregation() -> None:
    frames = {
        "mapping_rows": pd.DataFrame(
            [
                {
                    "variable_id": "v1",
                    "field_id": "v1",
                    "mapping_name": "request",
                    "display": "amount",
                },
                {
                    "variable_id": "v1",
                    "field_id": "v1",
                    "mapping_name": "response",
                    "display": "result",
                },
                {
                    "variable_id": "v1",
                    "field_id": "v1",
                    "mapping_name": "response",
                    "display": "status",
                },
                {
                    "variable_id": "v2",
                    "field_id": "v2",
                    "mapping_name": "request",
                    "display": "term",
                },
            ]
        )
    }

    out = pivot_frame(
        frames,
        source="mapping_rows",
        output="mapping_view",
        index_columns=["variable_id", "field_id"],
        column_key="mapping_name",
        value_column="display",
        column_keys=["request", "response", "audit"],
        fill_value="",
        duplicates="aggregate",
        aggregation="join",
        separator=" | ",
    )

    assert out["mapping_view"].to_dict(orient="records") == [
        {
            "variable_id": "v1",
            "field_id": "v1",
            "request": "amount",
            "response": "result | status",
            "audit": "",
        },
        {
            "variable_id": "v2",
            "field_id": "v2",
            "request": "term",
            "response": "",
            "audit": "",
        },
    ]
    assert list(out["mapping_view"].columns) == [
        "variable_id",
        "field_id",
        "request",
        "response",
        "audit",
    ]


def test_pivot_frame_fails_on_duplicate_cells_without_explicit_aggregation() -> None:
    frames = {
        "mapping_rows": pd.DataFrame(
            [
                {"variable_id": "v1", "mapping_name": "request", "display": "amount"},
                {"variable_id": "v1", "mapping_name": "request", "display": "amount_alt"},
            ]
        )
    }

    with pytest.raises(ValueError, match="duplicate pivot cells"):
        pivot_frame(
            frames,
            source="mapping_rows",
            output="mapping_view",
            index_columns=["variable_id"],
            column_key="mapping_name",
            value_column="display",
        )


def test_pivot_frame_fails_clearly_for_missing_and_unexpected_columns() -> None:
    frames = {
        "mapping_rows": pd.DataFrame(
            [{"variable_id": "v1", "mapping_name": "request", "display": "amount"}]
        )
    }

    with pytest.raises(KeyError, match="missing configured"):
        pivot_frame(
            frames,
            source="mapping_rows",
            output="mapping_view",
            index_columns=["variable_id", "field_id"],
            column_key="mapping_name",
            value_column="display",
        )

    with pytest.raises(ValueError, match="not listed in column_keys"):
        pivot_frame(
            frames,
            source="mapping_rows",
            output="mapping_view",
            index_columns=["variable_id"],
            column_key="mapping_name",
            value_column="display",
            column_keys=["response"],
        )


def test_pivot_frame_marks_output_as_readonly_projection_by_default() -> None:
    frames = {
        "mapping_rows": pd.DataFrame(
            [{"variable_id": "v1", "mapping_name": "request", "display": "amount"}]
        )
    }

    out = pivot_frame(
        frames,
        source="mapping_rows",
        output="mapping_view",
        index_columns=["variable_id"],
        column_key="mapping_name",
        value_column="display",
        name="request_mapping_view",
    )

    assert "_meta" not in out


def test_extract_frame_composes_with_pivot_frame_through_pipeline_registry() -> None:
    frames = {
        "raw_mappings": pd.DataFrame(
            [
                {
                    "variable_id": "v2",
                    "field_id": "v2",
                    "mapping_name": "request",
                    "display": "term",
                    "active": True,
                },
                {
                    "variable_id": "v1",
                    "field_id": "v1",
                    "mapping_name": "request",
                    "display": "amount",
                    "active": True,
                },
                {
                    "variable_id": "v1",
                    "field_id": "v1",
                    "mapping_name": "response",
                    "display": "result",
                    "active": True,
                },
                {
                    "variable_id": "v3",
                    "field_id": "v3",
                    "mapping_name": "request",
                    "display": "deprecated",
                    "active": False,
                },
            ]
        )
    }

    steps = build_steps_from_config(
        [
            {
                "step": "extract_frame",
                "source": "raw_mappings",
                "output": "active_mappings",
                "columns": ["variable_id", "field_id", "mapping_name", "display"],
                "where": {"column": "active", "equals": True},
                "sort_by": ["variable_id", "field_id"],
            },
            {
                "step": "pivot_frame",
                "source": "active_mappings",
                "output": "mapping_view",
                "index_columns": ["variable_id", "field_id"],
                "column_key": "mapping_name",
                "value_column": "display",
                "column_keys": ["request", "response"],
            },
        ]
    )

    out = run_pipeline(frames, steps)

    assert out["mapping_view"].to_dict(orient="records") == [
        {"variable_id": "v1", "field_id": "v1", "request": "amount", "response": "result"},
        {"variable_id": "v2", "field_id": "v2", "request": "term", "response": ""},
    ]
