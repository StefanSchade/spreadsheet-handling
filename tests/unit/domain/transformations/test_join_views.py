from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.frame_lifecycle import frame_lifecycle
from spreadsheet_handling.domain.transformations.join_views import join_frames
from spreadsheet_handling.pipeline.registry import build_steps_from_config, run_pipeline

pytestmark = pytest.mark.ftr("FTR-SIMPLE-JOIN-VIEWS-P4A")


def test_join_frames_left_join_selects_and_renames_columns() -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {"variable_id": "v1", "label": "Rate"},
                {"variable_id": "v2", "label": "Amount"},
            ]
        ),
        "metadata": pd.DataFrame(
            [
                {"variable_id": "v1", "component": "cashflow", "label": "Installment"},
            ]
        ),
    }

    out = join_frames(
        frames,
        left="variables",
        right="metadata",
        output="variable_view",
        key="variable_id",
        how="left",
        left_columns=["variable_id", "label"],
        right_columns=["component", "label"],
        right_rename={"label": "display_label"},
    )

    assert out["variable_view"].to_dict(orient="records") == [
        {
            "variable_id": "v1",
            "label": "Rate",
            "component": "cashflow",
            "display_label": "Installment",
        },
        {
            "variable_id": "v2",
            "label": "Amount",
            "component": "",
            "display_label": "",
        },
    ]


def test_join_frames_inner_join_drops_unmatched_rows() -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {"variable_id": "v1", "label": "Rate"},
                {"variable_id": "v2", "label": "Amount"},
            ]
        ),
        "metadata": pd.DataFrame([{"variable_id": "v1", "component": "cashflow"}]),
    }

    out = join_frames(
        frames,
        left="variables",
        right="metadata",
        output="variable_view",
        key="variable_id",
        how="inner",
    )

    assert out["variable_view"].to_dict(orient="records") == [
        {"variable_id": "v1", "label": "Rate", "component": "cashflow"},
    ]


def test_join_frames_semi_join_filters_entities_through_expanded_tuple_relation() -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {"variable_id": "v1", "label": "Rate"},
                {"variable_id": "v2", "label": "Amount"},
                {"variable_id": "v3", "label": "Term"},
            ]
        ),
        "variable_product_codes": pd.DataFrame(
            [
                {"variable_id": "v1", "product_id": "annuity", "marker": "output"},
                {"variable_id": "v1", "product_id": "bullet", "marker": "input"},
                {"variable_id": "v2", "product_id": "annuity", "marker": "input"},
                {"variable_id": "v3", "product_id": "annuity", "marker": "output"},
            ]
        ),
    }

    out = join_frames(
        frames,
        left="variables",
        right="variable_product_codes",
        output="output_variables",
        key="variable_id",
        how="semi",
        left_columns=["variable_id", "label"],
        right_where={"column": "marker", "equals": "output"},
    )

    assert out["output_variables"].to_dict(orient="records") == [
        {"variable_id": "v1", "label": "Rate"},
        {"variable_id": "v3", "label": "Term"},
    ]


def test_join_frames_supports_composite_and_differently_named_keys() -> None:
    frames = {
        "operation_slots": pd.DataFrame(
            [
                {"operation_id": "op1", "slot_id": "primary", "label": "Primary target"},
                {"operation_id": "op1", "slot_id": "secondary", "label": "Secondary target"},
            ]
        ),
        "slot_details": pd.DataFrame(
            [
                {
                    "operation": "op1",
                    "slot": "primary",
                    "variable_id": "v1",
                }
            ]
        ),
    }

    out = join_frames(
        frames,
        left="operation_slots",
        right="slot_details",
        output="operation_slot_view",
        left_keys=["operation_id", "slot_id"],
        right_keys=["operation", "slot"],
        how="left",
        right_columns=["variable_id"],
    )

    assert out["operation_slot_view"].to_dict(orient="records") == [
        {
            "operation_id": "op1",
            "slot_id": "primary",
            "label": "Primary target",
            "variable_id": "v1",
        },
        {
            "operation_id": "op1",
            "slot_id": "secondary",
            "label": "Secondary target",
            "variable_id": "",
        },
    ]


def test_join_frames_fails_for_missing_keys_and_duplicate_right_keys() -> None:
    frames = {
        "variables": pd.DataFrame([{"variable_id": "v1", "label": "Rate"}]),
        "metadata": pd.DataFrame(
            [
                {"variable_id": "v1", "component": "cashflow"},
                {"variable_id": "v1", "component": "pricing"},
            ]
        ),
    }

    with pytest.raises(KeyError, match="missing configured join key"):
        join_frames(
            frames,
            left="variables",
            right="metadata",
            output="broken",
            key="missing",
        )

    with pytest.raises(ValueError, match="duplicate join key"):
        join_frames(
            frames,
            left="variables",
            right="metadata",
            output="broken",
            key="variable_id",
        )


def test_join_frames_does_not_match_empty_join_keys() -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {"variable_id": "v1", "label": "Rate"},
                {"variable_id": "", "label": "Broken"},
            ]
        ),
        "metadata": pd.DataFrame(
            [
                {"variable_id": "", "component": "should_not_match"},
                {"variable_id": "v1", "component": "cashflow"},
            ]
        ),
    }

    out = join_frames(
        frames,
        left="variables",
        right="metadata",
        output="variable_view",
        key="variable_id",
        how="left",
    )

    assert out["variable_view"].to_dict(orient="records") == [
        {"variable_id": "v1", "label": "Rate", "component": "cashflow"},
        {"variable_id": "", "label": "Broken", "component": ""},
    ]


def test_join_frames_requires_explicit_collision_handling_or_suffixes() -> None:
    frames = {
        "variables": pd.DataFrame([{"variable_id": "v1", "label": "Rate"}]),
        "metadata": pd.DataFrame([{"variable_id": "v1", "label": "Installment"}]),
    }

    with pytest.raises(ValueError, match="colliding column"):
        join_frames(
            frames,
            left="variables",
            right="metadata",
            output="variable_view",
            key="variable_id",
            right_columns=["label"],
        )

    out = join_frames(
        frames,
        left="variables",
        right="metadata",
        output="variable_view",
        key="variable_id",
        right_columns=["label"],
        collisions="suffix",
        suffixes=["_source", "_metadata"],
    )

    assert out["variable_view"].to_dict(orient="records") == [
        {
            "variable_id": "v1",
            "label_source": "Rate",
            "label_metadata": "Installment",
        }
    ]


def test_join_frames_applies_post_join_where_to_output_columns() -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {"variable_id": "v1", "label": "Rate"},
                {"variable_id": "v2", "label": "Amount"},
            ]
        ),
        "metadata": pd.DataFrame(
            [
                {"variable_id": "v1", "component": "cashflow"},
                {"variable_id": "v2", "component": "pricing"},
            ]
        ),
    }

    out = join_frames(
        frames,
        left="variables",
        right="metadata",
        output="cashflow_variables",
        key="variable_id",
        how="inner",
        where={"column": "component", "equals": "cashflow"},
    )

    assert out["cashflow_variables"].to_dict(orient="records") == [
        {"variable_id": "v1", "label": "Rate", "component": "cashflow"},
    ]


def test_join_frames_marks_output_as_readonly_projection_by_default() -> None:
    frames = {
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "metadata": pd.DataFrame([{"variable_id": "v1", "component": "cashflow"}]),
    }

    out = join_frames(
        frames,
        left="variables",
        right="metadata",
        output="variable_view",
        key="variable_id",
        name="variable_metadata_view",
    )

    lifecycle = frame_lifecycle(out["_meta"])
    assert lifecycle["variable_view"] == {
        "role": "readonly_projection",
        "canonical": False,
        "editable": False,
        "render": "visible_by_default",
        "derived_from": ["variables", "metadata"],
        "produced_by": {"step": "join_frames", "name": "variable_metadata_view"},
    }
    assert lifecycle["variables"]["role"] == "canonical_source"
    assert lifecycle["metadata"]["role"] == "canonical_source"


def test_join_frames_is_config_addressable_in_a_pipeline() -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {"variable_id": "v1", "label": "Rate"},
                {"variable_id": "v2", "label": "Amount"},
            ]
        ),
        "metadata": pd.DataFrame([{"variable_id": "v1", "component": "cashflow"}]),
    }
    steps = build_steps_from_config(
        [
            {
                "step": "join_frames",
                "left": "variables",
                "right": "metadata",
                "output": "variable_view",
                "key": "variable_id",
                "how": "left",
            }
        ]
    )

    out = run_pipeline(frames, steps)

    assert out["variable_view"].to_dict(orient="records") == [
        {"variable_id": "v1", "label": "Rate", "component": "cashflow"},
        {"variable_id": "v2", "label": "Amount", "component": ""},
    ]
