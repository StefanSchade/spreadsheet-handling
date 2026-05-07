from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.spreadsheet_contract import build_spreadsheet_render_plan
from spreadsheet_handling.rendering.frame_selection import select_render_frames

pytestmark = pytest.mark.ftr("FTR-FRAME-LIFECYCLE-AND-WORKBOOK-VIEWS-P4")


def _frames_with_meta(meta: dict) -> dict:
    return {
        "orders_raw": pd.DataFrame({"id": [1]}),
        "orders_view": pd.DataFrame({"id": [1]}),
        "_meta": meta,
    }


def test_render_plan_omits_only_explicit_lifecycle_frames_when_view_policy_requests_it() -> None:
    meta = {
        "workbook_view": {"mode": "editable", "drop_redundant_data": True},
        "frame_lifecycle": {
            "orders_raw": {
                "role": "intermediate",
                "canonical": False,
                "editable": False,
                "render": "omit_by_default",
                "derived_from": [],
                "superseded_by": ["orders_view"],
            },
            "orders_view": {
                "role": "editable_projection",
                "canonical": False,
                "editable": True,
                "render": "visible_by_default",
                "derived_from": ["orders_raw"],
            },
        },
    }

    plan = build_spreadsheet_render_plan(_frames_with_meta(meta), meta)

    assert "orders_raw" not in plan.sheet_order
    assert "orders_view" in plan.sheet_order


def test_render_plan_preserves_current_visibility_without_workbook_view_policy() -> None:
    meta = {
        "frame_lifecycle": {
            "orders_raw": {
                "role": "intermediate",
                "canonical": False,
                "editable": False,
                "render": "omit_by_default",
            }
        }
    }

    plan = build_spreadsheet_render_plan(_frames_with_meta(meta), meta)

    assert "orders_raw" in plan.sheet_order
    assert "orders_view" in plan.sheet_order


def test_render_selection_does_not_infer_lifecycle_from_raw_suffix() -> None:
    meta = {
        "workbook_view": {"mode": "editable", "drop_redundant_data": True},
        "frame_lifecycle": {
            "orders_view": {
                "role": "editable_projection",
                "canonical": False,
                "editable": True,
                "render": "visible_by_default",
            }
        },
    }

    selected = select_render_frames(_frames_with_meta(meta), meta)

    assert "orders_raw" in selected
    assert "orders_view" in selected


def test_render_selection_does_not_omit_derived_frames_without_omit_policy() -> None:
    meta = {
        "workbook_view": {"mode": "editable", "drop_redundant_data": True},
        "frame_lifecycle": {
            "orders_view": {
                "role": "editable_projection",
                "canonical": False,
                "editable": True,
                "render": "visible_by_default",
                "derived_from": ["orders_raw"],
            }
        },
    }

    selected = select_render_frames(_frames_with_meta(meta), meta)

    assert "orders_view" in selected


def test_unknown_frame_policy_can_fail_unclassified_frames() -> None:
    meta = {
        "workbook_view": {
            "mode": "editable",
            "drop_redundant_data": True,
            "unknown_frame_policy": "fail",
        },
        "frame_lifecycle": {},
    }

    with pytest.raises(ValueError, match="orders_raw"):
        select_render_frames(_frames_with_meta(meta), meta)


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
