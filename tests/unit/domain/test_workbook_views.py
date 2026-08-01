from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.exact_table import ExactTable
from spreadsheet_handling.domain.transformations.grouped_xref import (
    GroupedMatrix,
    contract_grouped_xref,
)
from spreadsheet_handling.domain.workbook_views import (
    WorkbookViewSheetMapping,
    apply_workbook_view_sheet_mappings,
    configure_workbook_view,
    resolve_workbook_view_sheet_mappings,
)
from spreadsheet_handling.pipeline import build_steps_from_config, run_pipeline

pytestmark = pytest.mark.ftr("FTR-DECLARATIVE-WORKBOOK-VIEWS-P4A")

_GX_KEYS = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")


def _grouped_source() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "key": list(_GX_KEYS),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitaet", "Festzins", "Guthaben"],
        }
    )


def _grouped_relation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"row_id": rid, "column_key": key, "value": f"{rid}:{key}"}
            for rid in ("r1", "r2")
            for key in _GX_KEYS
        ]
    )


def _grouped_matrix() -> GroupedMatrix:
    return contract_grouped_xref(
        {"rel": _grouped_relation(), "src": _grouped_source()},
        relation="rel",
        output="Matrix",
        row_keys=["row_id"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )["Matrix"]


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


# --- GX-5: grouped-XRef workbook adoption ---------------------------------


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_configure_workbook_view_selects_grouped_matrix_by_identity_and_renames() -> None:
    gm = _grouped_matrix()
    frames = {"grouped": gm}

    out = configure_workbook_view(
        frames,
        sheets=[{"frame": "grouped", "sheet": "Rendered Matrix"}],
    )

    # The exact carrier is preserved: not unwrapped, copied, flattened, or converted.
    assert out["grouped"] is gm
    assert out["_meta"]["workbook_view"]["sheets"] == [
        {"frame": "grouped", "sheet": "Rendered Matrix", "order": 0}
    ]
    assert out["_meta"]["workbook_view"]["sheet_mappings"] == [
        {"sheet": "Rendered Matrix", "frame": "grouped"}
    ]
    # A grouped sheet without column-targeted options adds no sheet-options blob.
    assert "sheets" not in out["_meta"]


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_configure_workbook_view_preserves_mixed_dataframe_and_grouped_order() -> None:
    gm = _grouped_matrix()
    df = pd.DataFrame([{"variable_id": "v1"}])
    frames = {"grouped": gm, "flat": df}

    out = configure_workbook_view(
        frames,
        sheets=[
            {"frame": "flat", "sheet": "Flat"},
            {"frame": "grouped", "sheet": "Grouped"},
        ],
    )

    assert out["flat"] is df
    assert out["grouped"] is gm
    assert out["_meta"]["workbook_view"]["sheets"] == [
        {"frame": "flat", "sheet": "Flat", "order": 0},
        {"frame": "grouped", "sheet": "Grouped", "order": 1},
    ]


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_configure_workbook_view_grouped_missing_and_duplicate_sheet_errors() -> None:
    gm = _grouped_matrix()
    frames = {"grouped": gm, "flat": pd.DataFrame([{"x": 1}])}

    with pytest.raises(KeyError, match="missing frame"):
        configure_workbook_view(frames, sheets=[{"frame": "absent", "sheet": "Nope"}])

    with pytest.raises(ValueError, match="Duplicate workbook view sheet name"):
        configure_workbook_view(
            frames,
            sheets=[
                {"frame": "grouped", "sheet": "Shared"},
                {"frame": "flat", "sheet": "Shared"},
            ],
        )


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_configure_workbook_view_rejects_column_targeted_options_for_grouped_sheet() -> None:
    gm = _grouped_matrix()
    frames = {"grouped": gm}

    for ambiguous in (
        {"helper_columns": ["leaf"]},
        {"editable_columns": ["leaf"]},
        {"protection": {"editable_columns": ["leaf"]}},
        {"options": {"freeze_header": True}},
    ):
        with pytest.raises(ValueError, match="unsupported in GX-5"):
            configure_workbook_view(
                frames,
                sheets=[{"frame": "grouped", "sheet": "Grouped", **ambiguous}],
            )


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_configure_workbook_view_dataframe_options_unaffected_by_grouped_gate() -> None:
    df = pd.DataFrame([{"ID": "v1", "label": "Rate"}])

    out = configure_workbook_view(
        {"flat": df},
        sheets=[{"frame": "flat", "sheet": "Flat", "options": {"freeze_header": True}}],
    )

    assert out["flat"] is df
    assert out["_meta"]["sheets"]["Flat"] == {"freeze_header": True}


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_configure_workbook_view_grouped_rejection_leaves_frames_and_meta_unchanged() -> None:
    gm = _grouped_matrix()
    meta = {"existing": {"keep": True}}
    frames = {"grouped": gm, "_meta": meta}

    with pytest.raises(ValueError, match="unsupported in GX-5"):
        configure_workbook_view(
            frames,
            sheets=[{"frame": "grouped", "sheet": "Grouped", "helper_columns": ["leaf"]}],
        )

    assert frames["grouped"] is gm
    assert frames["_meta"] is meta
    assert meta == {"existing": {"keep": True}}
    assert "workbook_view" not in meta


@pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")
def test_apply_workbook_view_sheet_mappings_remaps_exact_table_visible_sheet() -> None:
    exact = ExactTable(
        header_grid=(("", "Kredit"), ("row_id", "Annuitaet")),
        data=(("r1", "r1:credit.annuity_loan"),),
        header_rows=2,
        n_cols=2,
    )
    frames = {
        "Rendered Matrix": exact,
        "_meta": {
            "workbook_view": {
                "sheet_mappings": [{"sheet": "Rendered Matrix", "frame": "grouped"}]
            }
        },
    }

    out = apply_workbook_view_sheet_mappings(frames, logical_frames=["grouped"])

    # An ExactTable read carrier counts as a projected visible sheet and is
    # re-keyed to its logical frame unchanged (preserved by identity).
    assert set(out) == {"grouped", "_meta"}
    assert "Rendered Matrix" not in out
    assert out["grouped"] is exact
