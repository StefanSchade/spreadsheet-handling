"""Tests for domain/validations/fk_helpers — pure FK-helper consistency checks.

FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5 made the FK-helper validation
primitives consume v2 relation policy at ``_meta.helper_policies.fk`` and
derived provenance under ``_meta.derived.sheets.*.helper_columns``. Tests
seed that policy explicitly via ``infer_fk_relations`` /
``configure_fk_helpers`` instead of relying on convention-driven detection.
"""
from __future__ import annotations

import pytest
import pandas as pd

from spreadsheet_handling.domain.fk_relations import infer_fk_relations
from spreadsheet_handling.domain.helper_policies import configure_fk_helpers
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
    """Build a two-sheet workbook (A references B via id_(B)) with v2 policy."""
    b = pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]})
    cols_a = {"id": [10, 20], "id_(B)": [1, 2]}
    if with_helper:
        cols_a["_B_name"] = helper_values or ["alpha", "beta"]
    a = pd.DataFrame(cols_a)
    return infer_fk_relations({"A": a, "B": b})


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
    return configure_fk_helpers(
        {"A": a, "B": b},
        target="B",
        key="id",
        allowed_helpers=["name", "category"],
        default_helpers=["name", "category"],
    )


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
        frames = infer_fk_relations({"A": a, "B": b})
        findings = check_unresolvable_fks(frames, DEFAULTS)
        assert len(findings) == 1
        assert findings[0].category == "unresolvable_fk"
        assert "99" in findings[0].detail

    def test_reports_unresolvable_fk_only_once_for_multi_helpers(self):
        b = pd.DataFrame({"id": [1], "name": ["alpha"], "category": ["x"]})
        a = pd.DataFrame({"id": [10], "id_(B)": [99]})
        frames = configure_fk_helpers(
            {"A": a, "B": b},
            target="B",
            key="id",
            allowed_helpers=["name", "category"],
            default_helpers=["name", "category"],
        )
        findings = check_unresolvable_fks(frames, DEFAULTS)
        assert len(findings) == 1
        assert findings[0].column == "id_(B)"


# --- check_unexpected_helpers ---

class TestUnexpectedHelpers:

    def test_no_unexpected(self):
        frames = _two_sheet_frames(with_helper=True)
        assert check_unexpected_helpers(frames, DEFAULTS) == []

    def test_arbitrary_underscored_column_not_flagged(self):
        """Post-FTR, ``unexpected_helper`` is no longer driven by the
        helper-prefix convention. A column not declared in policy /
        provenance is just a regular column and not reported.
        """
        a = pd.DataFrame({"id": [1], "id_(B)": [1], "_Z_name": ["orphan"]})
        b = pd.DataFrame({"id": [1], "name": ["alpha"]})
        frames = infer_fk_relations({"A": a, "B": b})
        findings = check_unexpected_helpers(frames, DEFAULTS)
        assert findings == []


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
        frames = _two_sheet_frames_multi_helper(include_name=True, include_category=False)
        findings = check_missing_helpers(frames, DEFAULTS)
        missing = [f for f in findings if f.column == "_B_category"]
        assert missing, findings


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
        frames = _two_sheet_frames_multi_helper(category_values=["WRONG", "y"])
        findings = check_helper_values(frames, DEFAULTS)
        category_findings = [f for f in findings if f.column == "_B_category"]
        assert category_findings, findings
        assert category_findings[0].category == "value_mismatch"


# --- validate_fk_helpers (combined) ---

class TestValidateAll:

    def test_clean_frames_with_helpers(self):
        frames = _two_sheet_frames(with_helper=True)
        assert validate_fk_helpers(frames, DEFAULTS) == []

    def test_multiple_findings(self):
        # missing helper + duplicate IDs
        b = pd.DataFrame({"id": [1, 1], "name": ["alpha", "alpha"]})
        a = pd.DataFrame({"id": [10], "id_(B)": [1]})
        frames = infer_fk_relations({"A": a, "B": b})
        findings = validate_fk_helpers(frames, DEFAULTS)
        kinds = {f.category for f in findings}
        assert "duplicate_id" in kinds
        assert "missing_helper" in kinds


@pytest.mark.ftr("FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5")
class TestValidateUsesTargetKeyFromPolicy:

    def test_helper_values_validated_against_policy_target_key(self):
        """Validation joins on the declared ``target_key``, not on a
        convention-derived id_field.
        """
        b = pd.DataFrame({"code": [1, 2], "name": ["alpha", "beta"]})
        a = pd.DataFrame(
            {"id": [10, 20], "code_(B)": [1, 2], "_B_name": ["WRONG", "beta"]}
        )
        frames = configure_fk_helpers(
            {"A": a, "B": b},
            target="B",
            key="code",
            allowed_helpers=["name"],
            default_helpers=["name"],
        )

        findings = check_helper_values(frames, DEFAULTS)
        assert any(
            f.category == "value_mismatch" and f.column == "_B_name"
            for f in findings
        ), findings

    def test_no_policy_no_provenance_returns_no_fk_findings(self):
        """Without policy / provenance there is no declared relation to
        validate; the FK-specific checks have nothing to report."""
        frames = {
            "A": pd.DataFrame({"id": [10], "id_(B)": [1], "_B_name": ["WRONG"]}),
            "B": pd.DataFrame({"id": [1], "name": ["alpha"]}),
        }
        assert check_helper_values(frames, DEFAULTS) == []
        assert check_missing_helpers(frames, DEFAULTS) == []
        assert check_unresolvable_fks(frames, DEFAULTS) == []
        assert check_unexpected_helpers(frames, DEFAULTS) == []
