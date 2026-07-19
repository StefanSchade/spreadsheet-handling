from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import LookupFormulaSpec, lookup_formula
from spreadsheet_handling.io_backends.spreadsheet_contract import build_spreadsheet_render_plan
from spreadsheet_handling.rendering.frame_selection import select_render_frames

pytestmark = [
    pytest.mark.ftr("FTR-FRAME-LIFECYCLE-AND-WORKBOOK-VIEWS-P4"),
    pytest.mark.ftr("FTR-IR-006-RENDER-INPUT-MUTATION-FIX"),
]


def _frames_with_meta(meta: dict) -> dict:
    return {
        "orders_raw": pd.DataFrame({"id": [1]}),
        "orders_view": pd.DataFrame({"id": [1]}),
        "_meta": meta,
    }


def test_render_plan_selects_every_remaining_frame_without_workbook_view() -> None:
    meta = {
        "frame_lifecycle": {
            "orders_raw": {
                "role": "system",
                "render": "never",
            },
        },
    }

    plan = build_spreadsheet_render_plan(_frames_with_meta(meta), meta)

    assert plan.sheet_order == ["orders_raw", "orders_view"]


def test_legacy_ontology_and_view_knobs_do_not_infer_selection() -> None:
    meta = {
        "workbook_view": {
            "mode": "editable",
            "drop_redundant_data": True,
            "unknown_frame_policy": "fail",
            "omit_roles": ["system"],
        },
        "frame_lifecycle": {
            "orders_raw": {
                "canonical": False,
                "role": "system",
                "render": "never",
                "derived_from": ["orders_view"],
                "superseded_by": ["orders_view"],
            },
            "orders_view": {"role": "redundant", "render": "omit_by_default"},
        }
    }

    selected = select_render_frames(_frames_with_meta(meta), meta)

    assert list(selected) == ["orders_raw", "orders_view", "_meta"]


@pytest.mark.ftr("FTR-DECLARATIVE-WORKBOOK-VIEWS-P4A")
def test_configured_workbook_view_selects_orders_and_renames_sheets() -> None:
    frames = {
        "variables_view": pd.DataFrame({"id": [1]}),
        "products_view": pd.DataFrame({"id": ["P-001"]}),
        "raw_variables": pd.DataFrame({"id": [1]}),
        "_meta": {},
    }
    meta = {
        "workbook_view": {
            "sheets": [
                {"frame": "products_view", "sheet": "Products"},
                {"frame": "variables_view", "sheet": "Variables"},
            ]
        }
    }

    selected = select_render_frames(frames, meta)

    assert list(selected) == ["Products", "Variables", "_meta"]
    assert selected["Products"] is frames["products_view"]
    assert selected["Variables"] is frames["variables_view"]
    assert "raw_variables" not in selected


@pytest.mark.ftr("FTR-DECLARATIVE-WORKBOOK-VIEWS-P4A")
def test_configured_workbook_view_fails_for_missing_or_duplicate_sheets() -> None:
    frames = {
        "variables_view": pd.DataFrame({"id": [1]}),
        "products_view": pd.DataFrame({"id": ["P-001"]}),
    }

    with pytest.raises(KeyError, match="missing frame"):
        select_render_frames(
            frames,
            {"workbook_view": {"sheets": [{"frame": "missing", "sheet": "Missing"}]}},
        )

    with pytest.raises(ValueError, match="Duplicate workbook view sheet name"):
        select_render_frames(
            frames,
            {
                "workbook_view": {
                    "sheets": [
                        {"frame": "variables_view", "sheet": "Overview"},
                        {"frame": "products_view", "sheet": "Overview"},
                    ]
                }
            },
        )


@pytest.mark.ftr("FTR-IR-006-RENDER-INPUT-MUTATION-FIX")
def test_workbook_view_rename_does_not_mutate_source_dataframe() -> None:
    formula = lookup_formula(
        source_key_column="id",
        lookup_sheet="products_view",
        lookup_key_column="id",
        lookup_value_column="name",
    )
    original_df = pd.DataFrame({"ref": [formula]})
    frames = {
        "products_view": pd.DataFrame({"id": [1], "name": ["Widget"]}),
        "orders_view": original_df,
    }
    meta = {
        "workbook_view": {
            "sheets": [
                {"frame": "products_view", "sheet": "Products"},
                {"frame": "orders_view", "sheet": "Orders"},
            ]
        }
    }

    selected = select_render_frames(frames, meta)

    # The render-local copy must carry the rewritten sheet name.
    rewritten_cell = selected["Orders"]["ref"].iloc[0]
    assert isinstance(rewritten_cell, LookupFormulaSpec)
    assert rewritten_cell.lookup_sheet == "Products"

    # The original caller-owned DataFrame must be unchanged.
    original_cell = original_df["ref"].iloc[0]
    assert isinstance(original_cell, LookupFormulaSpec)
    assert original_cell.lookup_sheet == "products_view"

    # The selected render copy must be a distinct object, not the original.
    assert selected["Orders"] is not original_df
