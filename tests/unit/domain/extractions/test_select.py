from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from spreadsheet_handling.domain.extractions.frame_extract import extract_frame
from spreadsheet_handling.domain.frame_lifecycle import frame_lifecycle


@pytest.mark.ftr("FTR-GENERIC-FRAME-EXTRACTIONS-P4A")
def test_extract_frame_can_copy_full_frame_without_mutating_source() -> None:
    source = pd.DataFrame(
        {
            "ID": ["v2", "v1"],
            "label": ["Amount", "Rate"],
            "active": [True, False],
        }
    )
    frames = {"variables": source}

    out = extract_frame(frames, source="variables", output="variables_copy")

    assert_frame_equal(out["variables_copy"], source)
    assert_frame_equal(frames["variables"], source)
    assert out["variables_copy"] is not source


@pytest.mark.ftr("FTR-GENERIC-FRAME-EXTRACTIONS-P4A")
def test_extract_frame_projects_filters_renames_adds_constants_and_sorts() -> None:
    source = pd.DataFrame(
        [
            {"ID": "v3", "label": "Fee", "component": "pricing", "active": True},
            {"ID": "v1", "label": "Rate", "component": "cashflow", "active": True},
            {"ID": "v2", "label": "Amount", "component": "cashflow", "active": False},
        ]
    )
    frames = {"variables": source}

    out = extract_frame(
        frames,
        source="variables",
        output="visible_variables",
        columns=["ID", "label", "component"],
        where={"column": "active", "equals": True},
        rename={"ID": "variable_id"},
        constants={"resource_type": "field_label"},
        sort_by=["component", "variable_id"],
    )

    assert out["visible_variables"].to_dict(orient="records") == [
        {
            "variable_id": "v1",
            "label": "Rate",
            "component": "cashflow",
            "resource_type": "field_label",
        },
        {
            "variable_id": "v3",
            "label": "Fee",
            "component": "pricing",
            "resource_type": "field_label",
        },
    ]
    assert list(out["visible_variables"].columns) == [
        "variable_id",
        "label",
        "component",
        "resource_type",
    ]
    assert "resource_type" not in frames["variables"].columns


@pytest.mark.ftr("FTR-GENERIC-FRAME-EXTRACTIONS-P4A")
def test_extract_frame_supports_membership_and_non_empty_predicates() -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {"ID": "v1", "kind": "input", "label": "Rate"},
                {"ID": "v2", "kind": "helper", "label": ""},
                {"ID": "v3", "kind": "output", "label": "Result"},
            ]
        )
    }

    member_out = extract_frame(
        frames,
        source="variables",
        output="io_variables",
        columns=["ID", "kind"],
        where={"column": "kind", "in": ["input", "output"]},
    )
    labeled_out = extract_frame(
        frames,
        source="variables",
        output="labeled_variables",
        columns=["ID"],
        where={"column": "label", "non_empty": True},
    )

    assert member_out["io_variables"].to_dict(orient="records") == [
        {"ID": "v1", "kind": "input"},
        {"ID": "v3", "kind": "output"},
    ]
    assert labeled_out["labeled_variables"].to_dict(orient="records") == [
        {"ID": "v1"},
        {"ID": "v3"},
    ]


@pytest.mark.ftr("FTR-GENERIC-FRAME-EXTRACTIONS-P4A")
def test_extract_frame_supports_null_predicates() -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {"ID": "v1", "deprecated_at": None},
                {"ID": "v2", "deprecated_at": "2026-01-01"},
            ]
        )
    }

    out = extract_frame(
        frames,
        source="variables",
        output="current_variables",
        where={"column": "deprecated_at", "is_null": True},
    )

    assert out["current_variables"].to_dict(orient="records") == [
        {"ID": "v1", "deprecated_at": ""},
    ]


@pytest.mark.ftr("FTR-GENERIC-FRAME-EXTRACTIONS-P4A")
def test_extract_frame_fails_clearly_for_missing_columns_and_unknown_predicates() -> None:
    frames = {"variables": pd.DataFrame({"ID": ["v1"], "active": [True]})}

    with pytest.raises(KeyError, match="missing configured columns"):
        extract_frame(
            frames,
            source="variables",
            output="broken",
            columns=["ID", "label"],
        )

    with pytest.raises(ValueError, match="Unsupported where predicate"):
        extract_frame(
            frames,
            source="variables",
            output="broken",
            where={"column": "active", "contains": "yes"},
        )


@pytest.mark.ftr("FTR-GENERIC-FRAME-EXTRACTIONS-P4A")
def test_extract_frame_marks_output_as_readonly_projection_by_default() -> None:
    frames = {"variables": pd.DataFrame({"ID": ["v1"]})}

    out = extract_frame(frames, source="variables", output="view")

    lifecycle = frame_lifecycle(out["_meta"])
    assert lifecycle["view"] == {
        "role": "readonly_projection",
        "canonical": False,
        "editable": False,
        "render": "visible_by_default",
        "derived_from": ["variables"],
        "produced_by": {"step": "extract_frame", "name": "extract_frame"},
    }
    assert lifecycle["variables"]["role"] == "canonical_source"


@pytest.mark.ftr("FTR-GENERIC-FRAME-EXTRACTIONS-P4A")
def test_extract_frame_allows_explicit_lifecycle_override() -> None:
    frames = {"variables": pd.DataFrame({"ID": ["v1"]})}

    out = extract_frame(
        frames,
        source="variables",
        output="editable_view",
        lifecycle={"role": "editable_projection", "editable": True},
    )

    lifecycle = frame_lifecycle(out["_meta"])
    assert lifecycle["editable_view"]["role"] == "editable_projection"
    assert lifecycle["editable_view"]["editable"] is True
