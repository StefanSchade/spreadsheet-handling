from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import LookupFormulaSpec, lookup_formula
from spreadsheet_handling.domain.transformations.grouped_xref import (
    GroupedMatrix,
    contract_grouped_xref,
)
from spreadsheet_handling.io_backends.spreadsheet_contract import build_spreadsheet_render_plan
from spreadsheet_handling.rendering.frame_selection import select_render_frames

pytestmark = [
    pytest.mark.ftr("FTR-FRAME-LIFECYCLE-AND-WORKBOOK-VIEWS-P4"),
    pytest.mark.ftr("FTR-IR-006-RENDER-INPUT-MUTATION-FIX"),
]

_GX_KEYS = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")


def _grouped_matrix() -> GroupedMatrix:
    relation = pd.DataFrame(
        [
            {"row_id": rid, "column_key": key, "value": f"{rid}:{key}"}
            for rid in ("r1", "r2")
            for key in _GX_KEYS
        ]
    )
    source = pd.DataFrame(
        {
            "key": list(_GX_KEYS),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitaet", "Festzins", "Guthaben"],
        }
    )
    return contract_grouped_xref(
        {"rel": relation, "src": source},
        relation="rel",
        output="Matrix",
        row_keys=["row_id"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )["Matrix"]


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


# --- GX-5: grouped-XRef workbook adoption ---------------------------------


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_configured_selection_includes_grouped_matrix_by_identity_and_renames() -> None:
    gm = _grouped_matrix()
    df = pd.DataFrame({"id": [1]})
    frames = {"grouped": gm, "flat": df, "excluded": _grouped_matrix(), "_meta": {}}
    meta = {
        "workbook_view": {
            "sheets": [
                {"frame": "flat", "sheet": "Flat"},
                {"frame": "grouped", "sheet": "Rendered Matrix"},
            ]
        }
    }

    selected = select_render_frames(frames, meta)

    # Declaration order, include/exclude, rename, and carrier identity together.
    assert list(selected) == ["Flat", "Rendered Matrix", "_meta"]
    assert selected["Flat"] is df
    assert selected["Rendered Matrix"] is gm
    assert "excluded" not in selected


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_configured_grouped_selection_rejects_missing_and_duplicate_names() -> None:
    frames = {"grouped": _grouped_matrix(), "flat": pd.DataFrame({"id": [1]})}

    with pytest.raises(KeyError, match="missing frame"):
        select_render_frames(
            frames,
            {"workbook_view": {"sheets": [{"frame": "absent", "sheet": "X"}]}},
        )

    with pytest.raises(ValueError, match="Duplicate workbook view sheet name"):
        select_render_frames(
            frames,
            {
                "workbook_view": {
                    "sheets": [
                        {"frame": "grouped", "sheet": "Shared"},
                        {"frame": "flat", "sheet": "Shared"},
                    ]
                }
            },
        )


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_grouped_carrier_is_not_formula_rewritten_but_dataframe_still_is() -> None:
    gm = _grouped_matrix()
    formula = lookup_formula(
        source_key_column="id",
        lookup_sheet="products_view",
        lookup_key_column="id",
        lookup_value_column="name",
    )
    frames = {
        "products_view": pd.DataFrame({"id": [1], "name": ["Widget"]}),
        "orders_view": pd.DataFrame({"ref": [formula]}),
        "grouped": gm,
    }
    meta = {
        "workbook_view": {
            "sheets": [
                {"frame": "products_view", "sheet": "Products"},
                {"frame": "orders_view", "sheet": "Orders"},
                {"frame": "grouped", "sheet": "Grouped"},
            ]
        }
    }

    selected = select_render_frames(frames, meta)

    # Formula sheet-name rewriting stays DataFrame-only.
    assert selected["Orders"]["ref"].iloc[0].lookup_sheet == "Products"
    # The grouped carrier is retained by identity and never inspected for formulas.
    assert selected["Grouped"] is gm


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_configured_selection_rejects_unsupported_non_renderable_value() -> None:
    frames = {"weird": object(), "flat": pd.DataFrame({"id": [1]})}

    with pytest.raises(TypeError, match="must be a .*DataFrame or GroupedMatrix"):
        select_render_frames(
            frames,
            {"workbook_view": {"sheets": [{"frame": "weird", "sheet": "W"}]}},
        )


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_default_path_passes_grouped_carrier_through_unchanged() -> None:
    gm = _grouped_matrix()
    frames = {"grouped": gm, "flat": pd.DataFrame({"id": [1]})}

    selected = select_render_frames(frames, None)

    assert list(selected) == ["grouped", "flat"]
    assert selected["grouped"] is gm
