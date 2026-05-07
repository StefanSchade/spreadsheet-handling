from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.frame_lifecycle import frame_lifecycle
from spreadsheet_handling.domain.workbook_views import configure_workbook_view
from spreadsheet_handling.pipeline.registry import build_steps_from_config, run_pipeline

pytestmark = pytest.mark.ftr("FTR-DECLARATIVE-WORKBOOK-VIEWS-P4A")


def test_configure_workbook_view_writes_sheet_order_names_and_lifecycle() -> None:
    frames = {
        "variables_view": pd.DataFrame([{"variable_id": "v1", "label": "Rate"}]),
        "product_matrix": pd.DataFrame([{"variable_id": "v1", "P-001": "output"}]),
        "raw_variables": pd.DataFrame([{"variable_id": "v1"}]),
    }

    out = configure_workbook_view(
        frames,
        sheets=[
            {
                "frame": "variables_view",
                "sheet": "Variables",
                "lifecycle": {"role": "editable_projection", "editable": True},
                "options": {"freeze_header": True},
            },
            {"frame": "product_matrix", "sheet": "Variable Matrix"},
        ],
        name="consumer_editable_view",
    )

    assert out["variables_view"] is frames["variables_view"]
    assert out["product_matrix"] is frames["product_matrix"]
    assert out["_meta"]["workbook_view"] == {
        "mode": "editable",
        "drop_redundant_data": True,
        "unknown_frame_policy": "fail",
        "sheets": [
            {"frame": "variables_view", "sheet": "Variables", "order": 0},
            {"frame": "product_matrix", "sheet": "Variable Matrix", "order": 1},
        ],
        "name": "consumer_editable_view",
    }
    assert out["_meta"]["sheets"]["Variables"] == {"freeze_header": True}

    lifecycle = frame_lifecycle(out["_meta"])
    assert lifecycle["variables_view"]["role"] == "editable_projection"
    assert lifecycle["variables_view"]["editable"] is True
    assert lifecycle["variables_view"]["render"] == "visible_by_default"
    assert lifecycle["product_matrix"]["role"] == "readonly_projection"
    assert "raw_variables" not in lifecycle


def test_configure_workbook_view_preserves_existing_canonical_lifecycle() -> None:
    frames = {
        "products": pd.DataFrame([{"product_id": "P-001"}]),
        "_meta": {
            "frame_lifecycle": {
                "products": {
                    "role": "canonical_source",
                    "canonical": True,
                    "editable": False,
                    "render": "visible_by_default",
                    "derived_from": [],
                }
            }
        },
    }

    out = configure_workbook_view(
        frames,
        sheets=[{"frame": "products", "sheet": "Products"}],
    )

    assert frame_lifecycle(out["_meta"])["products"]["role"] == "canonical_source"
    assert frame_lifecycle(out["_meta"])["products"]["canonical"] is True


def test_configure_workbook_view_accepts_mapping_shorthand() -> None:
    frames = {"variables_view": pd.DataFrame([{"variable_id": "v1"}])}

    out = configure_workbook_view(frames, sheets={"variables_view": "Variables"})

    assert out["_meta"]["workbook_view"]["sheets"] == [
        {"frame": "variables_view", "sheet": "Variables", "order": 0}
    ]


def test_configure_workbook_view_rejects_missing_duplicate_and_transform_specs() -> None:
    frames = {
        "variables_view": pd.DataFrame([{"variable_id": "v1"}]),
        "products_view": pd.DataFrame([{"product_id": "P-001"}]),
    }

    with pytest.raises(KeyError, match="missing frame"):
        configure_workbook_view(frames, sheets=[{"frame": "missing", "sheet": "Missing"}])

    with pytest.raises(ValueError, match="Duplicate workbook view sheet name"):
        configure_workbook_view(
            frames,
            sheets=[
                {"frame": "variables_view", "sheet": "Overview"},
                {"frame": "products_view", "sheet": "Overview"},
            ],
        )

    with pytest.raises(ValueError, match="transformation key"):
        configure_workbook_view(
            frames,
            sheets=[
                {
                    "frame": "variables_view",
                    "sheet": "Variables",
                    "where": {"column": "active", "equals": True},
                }
            ],
        )


def test_configure_workbook_view_is_config_addressable_in_pipeline() -> None:
    frames = {"variables_view": pd.DataFrame([{"variable_id": "v1"}])}
    steps = build_steps_from_config(
        [
            {
                "step": "configure_workbook_view",
                "sheets": [{"frame": "variables_view", "sheet": "Variables"}],
            }
        ]
    )

    out = run_pipeline(frames, steps)

    assert out["_meta"]["workbook_view"]["sheets"][0] == {
        "frame": "variables_view",
        "sheet": "Variables",
        "order": 0,
    }
