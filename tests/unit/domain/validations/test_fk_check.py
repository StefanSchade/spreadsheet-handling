"""Tests for domain/validations/fk_helpers — pure FK-helper consistency checks."""
from __future__ import annotations

import pytest
import pandas as pd

from spreadsheet_handling.domain.validations.fk_helpers import (
    FKFinding,
    check_duplicate_ids,
    check_missing_helpers,
    check_unexpected_helpers,
    check_helper_values,
    check_unresolvable_fks,
    validate_fk_helpers,
)

pytestmark = pytest.mark.ftr("FTR-FK-HELPER-REFACTOR-P3B")

DEFAULTS = {"id_field": "id", "label_field": "name", "helper_prefix": "_", "detect_fk": True}


def _two_sheet_frames(*, with_helper: bool = False, helper_values: list | None = None):
    """Build a minimal two-sheet frames dict (A references B via id_(B))."""
    b = pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]})
    cols_a = {"id": [10, 20], "id_(B)": [1, 2]}
    if with_helper:
        cols_a["_B_name"] = helper_values or ["alpha", "beta"]
    a = pd.DataFrame(cols_a)
    return {"A": a, "B": b}


def _two_sheet_frames_multi_helper(
    *,
    include_name: bool = True,
    include_category: bool = True,
    name_values: list | None = None,
    category_values: list | None = None,
):
    b = pd.DataFrame(
        {
            "id": [1, 2],
            "name": ["alpha", "beta"],
            "category": ["x", "y"],
        }
    )
    cols_a = {"id": [10, 20], "id_(B)": [1, 2]}
    if include_name:
        cols_a["_B_name"] = name_values or ["alpha", "beta"]
    if include_category:
        cols_a["_B_category"] = category_values or ["x", "y"]
    a = pd.DataFrame(cols_a)
    return {"A": a, "B": b}


# --- check_duplicate_ids ---

class TestDuplicateIds:

    def test_no_duplicates(self):
        frames = _two_sheet_frames()
        assert check_duplicate_ids(frames, DEFAULTS) == []

    def test_detects_duplicates(self):
        frames = {"X": pd.DataFrame({"id": [1, 1, 2], "name": ["a", "b", "c"]})}
        findings = check_duplicate_ids(frames, DEFAULTS)
        assert len(findings) == 1
        assert findings[0].category == "duplicate_id"
        assert findings[0].sheet == "X"
        assert "1" in findings[0].detail


# --- check_unresolvable_fks ---

class TestUnresolvableFks:

    def test_all_resolvable(self):
        frames = _two_sheet_frames()
        assert check_unresolvable_fks(frames, DEFAULTS) == []

    def test_detects_missing_target(self):
        b = pd.DataFrame({"id": [1], "name": ["alpha"]})
        a = pd.DataFrame({"id": [10], "id_(B)": [99]})  # 99 not in B
        findings = check_unresolvable_fks({"A": a, "B": b}, DEFAULTS)
        assert len(findings) == 1
        assert findings[0].category == "unresolvable_fk"
        assert "99" in findings[0].detail

    def test_reports_unresolvable_fk_only_once_for_multi_helpers(self):
        defaults = {**DEFAULTS, "helper_fields_by_fk": {"id_(B)": ["name", "category"]}}
        b = pd.DataFrame({"id": [1], "name": ["alpha"], "category": ["x"]})
        a = pd.DataFrame({"id": [10], "id_(B)": [99]})
        findings = check_unresolvable_fks({"A": a, "B": b}, defaults)
        assert len(findings) == 1
        assert findings[0].column == "id_(B)"


# --- check_unexpected_helpers ---

class TestUnexpectedHelpers:

    def test_no_unexpected(self):
        frames = _two_sheet_frames(with_helper=True)
        assert check_unexpected_helpers(frames, DEFAULTS) == []

    def test_detects_orphaned_helper(self):
        # _Z_name has no corresponding id_(Z) FK column
        a = pd.DataFrame({"id": [1], "_Z_name": ["orphan"]})
        findings = check_unexpected_helpers({"A": a}, DEFAULTS)
        assert len(findings) == 1
        assert findings[0].category == "unexpected_helper"
        assert findings[0].column == "_Z_name"


# --- check_missing_helpers ---

class TestMissingHelpers:

    def test_no_missing_when_present(self):
        frames = _two_sheet_frames(with_helper=True)
        assert check_missing_helpers(frames, DEFAULTS) == []

    def test_detects_missing_helper(self):
        frames = _two_sheet_frames(with_helper=False)
        findings = check_missing_helpers(frames, DEFAULTS)
        assert len(findings) == 1
        assert findings[0].category == "missing_helper"
        assert findings[0].column == "_B_name"

    def test_detects_missing_helper_for_multi_helper_config(self):
        defaults = {**DEFAULTS, "helper_fields_by_fk": {"id_(B)": ["name", "category"]}}
        frames = _two_sheet_frames_multi_helper(include_name=True, include_category=False)
        findings = check_missing_helpers(frames, defaults)
        assert len(findings) == 1
        assert findings[0].column == "_B_category"


# --- check_helper_values ---

class TestHelperValues:

    def test_correct_values(self):
        frames = _two_sheet_frames(with_helper=True, helper_values=["alpha", "beta"])
        assert check_helper_values(frames, DEFAULTS) == []

    def test_detects_wrong_value(self):
        frames = _two_sheet_frames(with_helper=True, helper_values=["WRONG", "beta"])
        findings = check_helper_values(frames, DEFAULTS)
        assert len(findings) == 1
        assert findings[0].category == "value_mismatch"
        assert "1 row(s)" in findings[0].detail

    def test_detects_wrong_value_for_second_helper_field(self):
        defaults = {**DEFAULTS, "helper_fields_by_fk": {"id_(B)": ["name", "category"]}}
        frames = _two_sheet_frames_multi_helper(category_values=["WRONG", "y"])
        findings = check_helper_values(frames, defaults)
        assert len(findings) == 1
        assert findings[0].column == "_B_category"


# --- validate_fk_helpers (combined) ---

class TestValidateAll:

    def test_clean_frames_with_helpers(self):
        frames = _two_sheet_frames(with_helper=True)
        assert validate_fk_helpers(frames, DEFAULTS) == []

    def test_multiple_findings(self):
        # missing helper + duplicate IDs
        b = pd.DataFrame({"id": [1, 1], "name": ["alpha", "alpha"]})
        a = pd.DataFrame({"id": [10], "id_(B)": [1]})
        findings = validate_fk_helpers({"A": a, "B": b}, DEFAULTS)
        kinds = {f.category for f in findings}
        assert "duplicate_id" in kinds
        assert "missing_helper" in kinds
