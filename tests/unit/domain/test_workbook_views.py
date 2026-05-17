from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.frame_lifecycle import frame_lifecycle
from spreadsheet_handling.domain.workbook_views import (
    WorkbookViewSheetMapping,
    configure_workbook_view,
    resolve_workbook_view_sheet_mappings,
)
from spreadsheet_handling.pipeline import build_steps_from_config, run_pipeline

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
        "sheet_mappings": [
            {"sheet": "Variables", "frame": "variables_view"},
            {"sheet": "Variable Matrix", "frame": "product_matrix"},
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
    assert out["_meta"]["workbook_view"]["sheet_mappings"] == [
        {"sheet": "Products", "frame": "products", "canonical_frame": "products"}
    ]


def test_configure_workbook_view_accepts_mapping_shorthand() -> None:
    frames = {"variables_view": pd.DataFrame([{"variable_id": "v1"}])}

    out = configure_workbook_view(frames, sheets={"variables_view": "Variables"})

    assert out["_meta"]["workbook_view"]["sheets"] == [
        {"frame": "variables_view", "sheet": "Variables", "order": 0}
    ]
    assert out["_meta"]["workbook_view"]["sheet_mappings"] == [
        {"sheet": "Variables", "frame": "variables_view"}
    ]


@pytest.mark.ftr("FTR-HELPER-COLUMN-STYLE-METADATA-P4A")
def test_configure_workbook_view_writes_helper_columns_to_sheet_options() -> None:
    frames = {
        "variables_view": pd.DataFrame(
            [{"ID": "v1", "value_label_de": "Rate", "data_type": "amount"}]
        )
    }

    out = configure_workbook_view(
        frames,
        sheets=[
            {
                "frame": "variables_view",
                "sheet": "Variables",
                "helper_columns": ["value_label_de", "data_type"],
                "options": {"helper_fill_rgb": "#FFF2CC"},
            }
        ],
    )

    assert out["_meta"]["sheets"]["Variables"] == {
        "helper_columns": ["value_label_de", "data_type"],
        "helper_fill_rgb": "#FFF2CC",
    }


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

    with pytest.raises(ValueError, match="Duplicate workbook view frame"):
        configure_workbook_view(
            frames,
            sheets=[
                {"frame": "variables_view", "sheet": "Overview"},
                {"frame": "variables_view", "sheet": "Variables"},
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

    with pytest.raises(ValueError, match="conflicting helper_columns"):
        configure_workbook_view(
            frames,
            sheets=[
                {
                    "frame": "variables_view",
                    "sheet": "Variables",
                    "helper_columns": ["value_label_de"],
                    "options": {"helper_columns": ["data_type"]},
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


def test_resolve_workbook_view_sheet_mappings_reads_hand_built_payload() -> None:
    meta = {
        "workbook_view": {
            "sheet_mappings": [
                {
                    "sheet": "Variables",
                    "frame": "variables_view",
                    "canonical_frame": "variables",
                },
                {"sheet": "Product Matrix", "frame": "product_matrix"},
            ]
        }
    }

    mapping = resolve_workbook_view_sheet_mappings(
        meta,
        visible_sheets=["Product Matrix", "Variables"],
        logical_frames=["variables", "variables_view", "product_matrix"],
    )

    assert mapping == {
        "Variables": WorkbookViewSheetMapping(
            visible_sheet="Variables",
            logical_frame="variables_view",
            canonical_frame="variables",
        ),
        "Product Matrix": WorkbookViewSheetMapping(
            visible_sheet="Product Matrix",
            logical_frame="product_matrix",
            canonical_frame=None,
        ),
    }


def test_resolve_workbook_view_sheet_mappings_fails_loudly_for_missing_and_malformed_meta() -> None:
    with pytest.raises(ValueError, match="sheet_mappings is required"):
        resolve_workbook_view_sheet_mappings({"workbook_view": {}})

    with pytest.raises(ValueError, match="sheet_mappings must be a list"):
        resolve_workbook_view_sheet_mappings({"workbook_view": {"sheet_mappings": {}}})

    with pytest.raises(ValueError, match="must be a mapping"):
        resolve_workbook_view_sheet_mappings({"workbook_view": {"sheet_mappings": ["Variables"]}})

    with pytest.raises(ValueError, match="Duplicate logical frame mapping"):
        resolve_workbook_view_sheet_mappings(
            {
                "workbook_view": {
                    "sheet_mappings": [
                        {"sheet": "Variables", "frame": "variables_view"},
                        {"sheet": "Variables Copy", "frame": "variables_view"},
                    ]
                }
            }
        )

    with pytest.raises(ValueError, match="not declared"):
        resolve_workbook_view_sheet_mappings(
            {
                "workbook_view": {
                    "sheet_mappings": [{"sheet": "Variables", "frame": "variables_view"}]
                }
            },
            visible_sheets=["Products"],
        )

    with pytest.raises(ValueError, match="missing required visible sheet"):
        resolve_workbook_view_sheet_mappings(
            {
                "workbook_view": {
                    "sheet_mappings": [{"sheet": "Variables", "frame": "variables_view"}]
                }
            },
            visible_sheets=[],
        )

    with pytest.raises(ValueError, match="unknown logical frame"):
        resolve_workbook_view_sheet_mappings(
            {
                "workbook_view": {
                    "sheet_mappings": [{"sheet": "Variables", "frame": "variables_view"}]
                }
            },
            logical_frames=["products_view"],
        )


def test_configure_workbook_view_persists_reverse_mapping_from_explicit_lifecycle() -> None:
    frames = {
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "variables_view": pd.DataFrame([{"variable_id": "v1", "label": "Rate"}]),
        "_meta": {
            "frame_lifecycle": {
                "variables": {
                    "role": "canonical_source",
                    "canonical": True,
                    "editable": False,
                    "render": "visible_by_default",
                    "derived_from": [],
                },
                "variables_view": {
                    "role": "editable_projection",
                    "canonical": False,
                    "editable": True,
                    "render": "visible_by_default",
                    "derived_from": ["variables"],
                },
            }
        },
    }

    out = configure_workbook_view(
        frames,
        sheets=[{"frame": "variables_view", "sheet": "Variables"}],
    )

    assert out["_meta"]["workbook_view"]["sheet_mappings"] == [
        {
            "sheet": "Variables",
            "frame": "variables_view",
            "canonical_frame": "variables",
        }
    ]


@pytest.mark.ftr("FTR-WORKBOOK-REIMPORT-VIEW-MAPPING-P4A")
def test_omitted_intermediate_frame_is_absent_from_sheet_mappings_and_resolves() -> None:
    frames = {
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "variables_view": pd.DataFrame([{"variable_id": "v1", "label": "Rate"}]),
        "variables_audit": pd.DataFrame([{"variable_id": "v1", "checked": True}]),
        "_meta": {
            "frame_lifecycle": {
                "variables": {
                    "role": "canonical_source",
                    "canonical": True,
                    "editable": False,
                    "render": "visible_by_default",
                    "derived_from": [],
                },
                "variables_view": {
                    "role": "editable_projection",
                    "canonical": False,
                    "editable": True,
                    "render": "visible_by_default",
                    "derived_from": ["variables"],
                },
                "variables_audit": {
                    "role": "intermediate",
                    "canonical": False,
                    "editable": False,
                    "render": "omit_by_default",
                    "derived_from": ["variables"],
                },
            }
        },
    }

    out = configure_workbook_view(
        frames,
        sheets=[{"frame": "variables_view", "sheet": "Variables"}],
    )

    sheet_mappings = out["_meta"]["workbook_view"]["sheet_mappings"]
    assert "variables_audit" not in {entry["frame"] for entry in sheet_mappings}
    assert sheet_mappings == [
        {
            "sheet": "Variables",
            "frame": "variables_view",
            "canonical_frame": "variables",
        }
    ]

    mapping = resolve_workbook_view_sheet_mappings(
        out["_meta"],
        visible_sheets=["Variables"],
        logical_frames=["variables", "variables_view", "variables_audit"],
    )

    assert mapping == {
        "Variables": WorkbookViewSheetMapping(
            visible_sheet="Variables",
            logical_frame="variables_view",
            canonical_frame="variables",
        )
    }
