from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.workbook_views import (
    WorkbookViewSheetMapping,
    apply_workbook_view_sheet_mappings,
    configure_workbook_view,
    resolve_workbook_view_sheet_mappings,
)
from spreadsheet_handling.pipeline import build_steps_from_config, run_pipeline

pytestmark = pytest.mark.ftr("FTR-DECLARATIVE-WORKBOOK-VIEWS-P4A")


def test_configure_workbook_view_writes_explicit_sheet_projection() -> None:
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
                "options": {"freeze_header": True},
            },
            {"frame": "product_matrix", "sheet": "Variable Matrix"},
        ],
        name="consumer_editable_view",
    )

    assert out["variables_view"] is frames["variables_view"]
    assert out["product_matrix"] is frames["product_matrix"]
    assert out["_meta"]["workbook_view"] == {
        "sheets": [
            {"frame": "variables_view", "sheet": "Variables", "order": 0},
            {"frame": "product_matrix", "sheet": "Variable Matrix", "order": 1},
        ],
        "sheet_mappings": [
            {"sheet": "Variables", "frame": "variables_view"},
            {"sheet": "Variable Matrix", "frame": "product_matrix"},
        ],
    }
    assert out["_meta"]["sheets"]["Variables"] == {"freeze_header": True}
    assert "frame_lifecycle" not in out["_meta"]


def test_configure_workbook_view_does_not_interpret_or_mutate_legacy_lifecycle() -> None:
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

    assert out["_meta"]["frame_lifecycle"] is frames["_meta"]["frame_lifecycle"]
    assert out["_meta"]["workbook_view"]["sheet_mappings"] == [
        {"sheet": "Products", "frame": "products"}
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

    with pytest.raises(ValueError, match="unsupported key"):
        configure_workbook_view(
            frames,
            sheets=[
                {
                    "frame": "variables_view",
                    "sheet": "Variables",
                    "lifecycle": {"render": "omit_by_default"},
                }
            ],
        )

    with pytest.raises(TypeError, match="unexpected keyword argument 'mode'"):
        configure_workbook_view(
            frames,
            sheets=[{"frame": "variables_view", "sheet": "Variables"}],
            mode="editable",  # type: ignore[call-arg]
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
    # The first entry carries a legacy derived "canonical_frame" key; it is
    # ignored on read. Mapping identity is visible sheet -> logical frame only.
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
        logical_frames=["variables_view", "product_matrix"],
    )

    assert mapping == {
        "Variables": WorkbookViewSheetMapping(
            visible_sheet="Variables",
            logical_frame="variables_view",
        ),
        "Product Matrix": WorkbookViewSheetMapping(
            visible_sheet="Product Matrix",
            logical_frame="product_matrix",
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


def test_configure_workbook_view_persists_frame_only_reverse_mapping() -> None:
    # The persisted mapping records visible sheet -> logical frame identity
    # only. No canonical_frame is derived from lifecycle metadata: the
    # projection/source relationship is feature-local transformation
    # knowledge, not generic mapping identity.
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
        {"sheet": "Variables", "frame": "variables_view"}
    ]


@pytest.mark.ftr("FTR-WORKBOOK-REIMPORT-VIEW-MAPPING-P4A")
def test_omitted_intermediate_frame_is_absent_from_sheet_mappings_and_resolves() -> None:
    frames = {
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "variables_view": pd.DataFrame([{"variable_id": "v1", "label": "Rate"}]),
        "variables_audit": pd.DataFrame([{"variable_id": "v1", "checked": True}]),
        "_meta": {},
    }

    out = configure_workbook_view(
        frames,
        sheets=[{"frame": "variables_view", "sheet": "Variables"}],
    )

    sheet_mappings = out["_meta"]["workbook_view"]["sheet_mappings"]
    assert "variables_audit" not in {entry["frame"] for entry in sheet_mappings}
    assert sheet_mappings == [
        {"sheet": "Variables", "frame": "variables_view"}
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
        )
    }


@pytest.mark.ftr("FTR-WORKBOOK-VIEW-ROUNDTRIP-RECOMPOSITION-P4A")
def test_apply_workbook_view_sheet_mappings_remaps_renamed_visible_sheet() -> None:
    df = pd.DataFrame([{"variable_id": "v1", "label": "Rate"}])
    frames = {
        "Editable Variables": df,
        "_meta": {
            "workbook_view": {
                "sheet_mappings": [
                    {
                        "sheet": "Editable Variables",
                        "frame": "variables_view",
                        "canonical_frame": "variables",
                    }
                ]
            }
        },
    }

    out = apply_workbook_view_sheet_mappings(frames)

    assert set(out) == {"variables_view", "_meta"}
    assert "Editable Variables" not in out
    pd.testing.assert_frame_equal(out["variables_view"], df)


@pytest.mark.ftr("FTR-WORKBOOK-VIEW-ROUNDTRIP-RECOMPOSITION-P4A")
def test_apply_workbook_view_sheet_mappings_is_order_independent() -> None:
    a = pd.DataFrame([{"x": 1}])
    b = pd.DataFrame([{"y": 2}])
    meta = {
        "workbook_view": {
            "sheet_mappings": [
                {"sheet": "Sheet A", "frame": "frame_a"},
                {"sheet": "Sheet B", "frame": "frame_b"},
            ]
        }
    }

    forward = apply_workbook_view_sheet_mappings(
        {"Sheet A": a, "Sheet B": b, "_meta": meta}
    )
    reversed_order = apply_workbook_view_sheet_mappings(
        {"_meta": meta, "Sheet B": b, "Sheet A": a}
    )

    assert set(forward) == set(reversed_order) == {"frame_a", "frame_b", "_meta"}
    pd.testing.assert_frame_equal(forward["frame_a"], reversed_order["frame_a"])
    pd.testing.assert_frame_equal(forward["frame_b"], reversed_order["frame_b"])


@pytest.mark.ftr("FTR-WORKBOOK-VIEW-ROUNDTRIP-RECOMPOSITION-P4A")
def test_apply_workbook_view_sheet_mappings_preserves_meta_unchanged() -> None:
    meta = {
        "workbook_view": {
            "sheet_mappings": [{"sheet": "S", "frame": "f"}],
        },
        "plugin_state": {"roundtrip": True},
    }
    expected_meta = {
        "workbook_view": {
            "sheet_mappings": [{"sheet": "S", "frame": "f"}],
        },
        "plugin_state": {"roundtrip": True},
    }
    frames = {"S": pd.DataFrame([{"a": 1}]), "_meta": meta}

    out = apply_workbook_view_sheet_mappings(frames)

    assert out["_meta"] is meta
    assert meta == expected_meta


@pytest.mark.ftr("FTR-WORKBOOK-VIEW-ROUNDTRIP-RECOMPOSITION-P4A")
def test_apply_workbook_view_sheet_mappings_fails_loudly_on_undeclared_sheet() -> None:
    frames = {
        "S": pd.DataFrame([{"a": 1}]),
        "Unexpected": pd.DataFrame([{"b": 2}]),
        "_meta": {
            "workbook_view": {"sheet_mappings": [{"sheet": "S", "frame": "f"}]}
        },
    }

    with pytest.raises(ValueError, match="not declared"):
        apply_workbook_view_sheet_mappings(frames)


@pytest.mark.ftr("FTR-WORKBOOK-VIEW-ROUNDTRIP-RECOMPOSITION-P4A")
def test_apply_workbook_view_sheet_mappings_is_config_addressable_in_pipeline() -> None:
    df = pd.DataFrame([{"a": 1}])
    frames = {
        "Editable": df,
        "_meta": {
            "workbook_view": {
                "sheet_mappings": [{"sheet": "Editable", "frame": "logical"}]
            }
        },
    }

    steps = build_steps_from_config([{"step": "apply_workbook_view_sheet_mappings"}])

    assert steps[0].name == "apply_workbook_view_sheet_mappings"
    assert steps[0].config["target"].endswith(":apply_workbook_view_sheet_mappings")

    out = run_pipeline(frames, steps)

    assert set(out) == {"logical", "_meta"}
    pd.testing.assert_frame_equal(out["logical"], df)
