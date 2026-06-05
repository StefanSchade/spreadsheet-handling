"""Unit tests for the shared presentation-metadata authority helper.

The helper is the single home for the replace-or-clear policy that both
backend parsers apply when projecting parsed carrier state into the
hidden ``workbook_meta_blob`` payload. See
``docs/backlog/FTR-PRESENTATION-META-CARRIER-AUTHORITY-P5.adoc``.

These tests pin the four-quadrant return-value truth table, the
preservation guarantees for unrelated metadata, and the assertion that
the helper does not create ``workbook_meta["sheets"]`` or per-sheet
entries on no-op clear paths.
"""

from __future__ import annotations

import copy

import pytest

from spreadsheet_handling.io_backends.presentation_meta import (
    apply_cell_addressed_presentation_meta,
)

pytestmark = pytest.mark.ftr("FTR-PRESENTATION-META-CARRIER-AUTHORITY-P5")


# ---------------------------------------------------------------------------
# Return-value truth table
# ---------------------------------------------------------------------------


def test_truth_table_replace_when_value_differs_returns_true():
    workbook_meta = {
        "sheets": {
            "Data": {"horizontal_alignments": {"A1": {"horizontal": "left"}}}
        }
    }
    new_value = {"A1": {"horizontal": "right"}}

    changed = apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", new_value
    )

    assert changed is True
    assert workbook_meta["sheets"]["Data"]["horizontal_alignments"] == new_value


def test_truth_table_no_op_when_value_equals_existing_returns_false():
    existing = {"A1": {"horizontal": "center"}}
    workbook_meta = {"sheets": {"Data": {"horizontal_alignments": existing}}}

    changed = apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", {"A1": {"horizontal": "center"}}
    )

    assert changed is False
    assert workbook_meta["sheets"]["Data"]["horizontal_alignments"] == existing


def test_truth_table_clear_when_entry_exists_returns_true():
    workbook_meta = {
        "sheets": {
            "Data": {
                "horizontal_alignments": {"A1": {"horizontal": "left"}},
                "text_orientations": {"A2": {"rotation": 90}},
            }
        }
    }

    changed = apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", None
    )

    assert changed is True
    assert "horizontal_alignments" not in workbook_meta["sheets"]["Data"]
    # Unrelated family on the same sheet is untouched.
    assert workbook_meta["sheets"]["Data"]["text_orientations"] == {
        "A2": {"rotation": 90}
    }


def test_truth_table_no_op_when_value_empty_and_entry_absent_returns_false():
    workbook_meta = {"sheets": {"Data": {"text_orientations": {"A2": {"rotation": 90}}}}}
    snapshot = copy.deepcopy(workbook_meta)

    changed = apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", None
    )

    assert changed is False
    assert workbook_meta == snapshot


@pytest.mark.parametrize("empty_value", [None, {}])
def test_clear_branch_accepts_none_and_empty_dict(empty_value):
    workbook_meta = {
        "sheets": {"Data": {"horizontal_alignments": {"A1": {"horizontal": "left"}}}}
    }

    changed = apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", empty_value
    )

    assert changed is True
    assert "horizontal_alignments" not in workbook_meta["sheets"]["Data"]


# ---------------------------------------------------------------------------
# No-create-on-no-op invariants
# ---------------------------------------------------------------------------


def test_clear_on_missing_sheets_dict_does_not_create_sheets_key():
    workbook_meta = {"author": "alice"}

    changed = apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", None
    )

    assert changed is False
    assert "sheets" not in workbook_meta
    assert workbook_meta == {"author": "alice"}


def test_clear_on_missing_sheet_entry_does_not_create_sheet_entry():
    workbook_meta = {"sheets": {"Other": {"horizontal_alignments": {"A1": {"horizontal": "left"}}}}}
    snapshot = copy.deepcopy(workbook_meta)

    changed = apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", None
    )

    assert changed is False
    assert "Data" not in workbook_meta["sheets"]
    assert workbook_meta == snapshot


def test_clear_on_present_sheet_without_family_does_not_modify_sheet_entry():
    workbook_meta = {"sheets": {"Data": {"text_orientations": {"A1": {"rotation": 90}}}}}
    snapshot = copy.deepcopy(workbook_meta)

    changed = apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", None
    )

    assert changed is False
    assert workbook_meta == snapshot


# ---------------------------------------------------------------------------
# Preservation guarantees (replace branch)
# ---------------------------------------------------------------------------


def test_replace_preserves_other_families_on_same_sheet():
    workbook_meta = {
        "sheets": {
            "Data": {
                "horizontal_alignments": {"A1": {"horizontal": "left"}},
                "text_orientations": {"A2": {"rotation": 90}},
                "column_widths": {"B": {"width": 20.0}},
            }
        }
    }

    apply_cell_addressed_presentation_meta(
        workbook_meta,
        "Data",
        "horizontal_alignments",
        {"A1": {"horizontal": "right"}},
    )

    sheet_meta = workbook_meta["sheets"]["Data"]
    assert sheet_meta["horizontal_alignments"] == {"A1": {"horizontal": "right"}}
    assert sheet_meta["text_orientations"] == {"A2": {"rotation": 90}}
    assert sheet_meta["column_widths"] == {"B": {"width": 20.0}}


def test_replace_preserves_other_sheets():
    workbook_meta = {
        "sheets": {
            "Data": {"horizontal_alignments": {"A1": {"horizontal": "left"}}},
            "Reference": {"horizontal_alignments": {"A1": {"horizontal": "center"}}},
        }
    }

    apply_cell_addressed_presentation_meta(
        workbook_meta,
        "Data",
        "horizontal_alignments",
        {"A1": {"horizontal": "right"}},
    )

    assert workbook_meta["sheets"]["Reference"] == {
        "horizontal_alignments": {"A1": {"horizontal": "center"}}
    }


def test_replace_preserves_top_level_workbook_keys():
    workbook_meta = {
        "author": "alice",
        "version": 2,
        "sheets": {"Data": {"horizontal_alignments": {"A1": {"horizontal": "left"}}}},
    }

    apply_cell_addressed_presentation_meta(
        workbook_meta,
        "Data",
        "horizontal_alignments",
        {"A1": {"horizontal": "right"}},
    )

    assert workbook_meta["author"] == "alice"
    assert workbook_meta["version"] == 2


# ---------------------------------------------------------------------------
# Preservation guarantees (clear branch)
# ---------------------------------------------------------------------------


def test_clear_preserves_other_families_on_same_sheet():
    workbook_meta = {
        "sheets": {
            "Data": {
                "horizontal_alignments": {"A1": {"horizontal": "left"}},
                "text_orientations": {"A2": {"rotation": 90}},
                "column_widths": {"B": {"width": 20.0}},
            }
        }
    }

    apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", None
    )

    sheet_meta = workbook_meta["sheets"]["Data"]
    assert "horizontal_alignments" not in sheet_meta
    assert sheet_meta["text_orientations"] == {"A2": {"rotation": 90}}
    assert sheet_meta["column_widths"] == {"B": {"width": 20.0}}


def test_clear_preserves_other_sheets():
    workbook_meta = {
        "sheets": {
            "Data": {"horizontal_alignments": {"A1": {"horizontal": "left"}}},
            "Reference": {"horizontal_alignments": {"A1": {"horizontal": "center"}}},
        }
    }

    apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", None
    )

    assert workbook_meta["sheets"]["Reference"] == {
        "horizontal_alignments": {"A1": {"horizontal": "center"}}
    }


def test_clear_preserves_top_level_workbook_keys():
    workbook_meta = {
        "author": "alice",
        "version": 2,
        "sheets": {"Data": {"horizontal_alignments": {"A1": {"horizontal": "left"}}}},
    }

    apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", "horizontal_alignments", None
    )

    assert workbook_meta["author"] == "alice"
    assert workbook_meta["version"] == 2


# ---------------------------------------------------------------------------
# Family-key agnosticism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "family_key,value",
    [
        ("horizontal_alignments", {"A1": {"horizontal": "left"}}),
        ("vertical_alignments", {"A1": {"vertical": "top"}}),
        ("text_orientations", {"A1": {"rotation": 90}}),
        ("column_widths", {"A": {"width": 20.0}}),
        # Dimension-keyed values are accepted unchanged — the helper does not
        # care about address shape and is intentionally not specific to
        # cell-addressed families despite the function name.
    ],
)
def test_helper_is_family_key_agnostic(family_key, value):
    workbook_meta: dict = {}

    changed = apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", family_key, value
    )
    assert changed is True
    assert workbook_meta["sheets"]["Data"][family_key] == value

    cleared = apply_cell_addressed_presentation_meta(
        workbook_meta, "Data", family_key, None
    )
    assert cleared is True
    assert family_key not in workbook_meta["sheets"]["Data"]
