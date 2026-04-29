"""Direct tests for domain.transformations.fk_helpers entry points.

FTR-FK-HELPER-DOMAIN-EXTRACTION: primary coverage for FK-helper semantics
lives here, testing the domain functions directly rather than via pipeline
step factories.
"""
from __future__ import annotations

import pytest
import pandas as pd

from spreadsheet_handling.domain.transformations.fk_helpers import (
    enrich_helpers,
    drop_helpers,
)
from spreadsheet_handling.rendering.formulas import LookupFormulaSpec

pytestmark = pytest.mark.ftr("FTR-FK-HELPER-DOMAIN-EXTRACTION")

DEFAULTS = {"id_field": "id", "label_field": "name", "helper_prefix": "_"}


def _frames():
    b = pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]})
    a = pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]})
    return {"A": a, "B": b}


# ---------------------------------------------------------------------------
# enrich_helpers
# ---------------------------------------------------------------------------

class TestEnrichHelpers:

    def test_adds_helper_column(self):
        out = enrich_helpers(_frames(), DEFAULTS)
        lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert "_B_name" in lvl0

    def test_helper_values_match_lookup(self):
        out = enrich_helpers(_frames(), DEFAULTS)
        helper_col = [c for c in out["A"].columns if (c[0] if isinstance(c, tuple) else c) == "_B_name"][0]
        assert out["A"][helper_col].tolist() == ["alpha", "beta"]

    def test_detect_fk_disabled_returns_unchanged(self):
        frames = _frames()
        out = enrich_helpers(frames, {**DEFAULTS, "detect_fk": False})
        assert out is frames

    def test_no_fk_columns_returns_without_helpers(self):
        frames = {"X": pd.DataFrame({"id": [1], "value": ["x"]})}
        out = enrich_helpers(frames, DEFAULTS)
        assert list(out["X"].columns) == ["id", "value"]

    def test_provenance_written(self):
        out = enrich_helpers(_frames(), DEFAULTS)
        prov = out["_meta"]["derived"]["sheets"]["A"]["helper_columns"]
        assert len(prov) == 1
        assert prov[0] == {
            "column": "_B_name",
            "fk_column": "id_(B)",
            "target": "B",
            "value_field": "name",
        }

    def test_no_provenance_for_sheet_without_fks(self):
        out = enrich_helpers(_frames(), DEFAULTS)
        derived_sheets = out["_meta"]["derived"]["sheets"]
        assert "B" not in derived_sheets

    def test_preserves_existing_meta(self):
        frames = _frames()
        frames["_meta"] = {"version": "3.0", "author": "test"}
        out = enrich_helpers(frames, DEFAULTS)
        assert out["_meta"]["version"] == "3.0"
        assert out["_meta"]["author"] == "test"
        assert "derived" in out["_meta"]

    def test_stale_provenance_removed(self):
        frames = _frames()
        frames["_meta"] = {
            "derived": {
                "sheets": {
                    "B": {
                        "helper_columns": [
                            {"column": "_X_old", "fk_column": "id_(X)",
                             "target": "X", "value_field": "old"},
                        ]
                    }
                }
            }
        }
        out = enrich_helpers(frames, DEFAULTS)
        derived_sheets = out["_meta"]["derived"]["sheets"]
        assert "B" not in derived_sheets
        assert "A" in derived_sheets

    def test_key_selective_merge_preserves_other_derived_keys(self):
        frames = _frames()
        frames["_meta"] = {
            "derived": {"sheets": {"A": {"other_derived_key": "keep_me"}}}
        }
        out = enrich_helpers(frames, DEFAULTS)
        sheet_derived = out["_meta"]["derived"]["sheets"]["A"]
        assert sheet_derived["other_derived_key"] == "keep_me"
        assert "helper_columns" in sheet_derived

    def test_multiple_helpers_in_configured_order(self):
        frames = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame(
                {"id": [1, 2], "name": ["alpha", "beta"], "category": ["x", "y"]}
            ),
        }
        defaults = {**DEFAULTS, "helper_fields_by_fk": {"id_(B)": ["category", "name"]}}
        out = enrich_helpers(frames, defaults)
        prov = out["_meta"]["derived"]["sheets"]["A"]["helper_columns"]
        assert len(prov) == 2
        assert prov[0]["column"] == "_B_category"
        assert prov[1]["column"] == "_B_name"

    @pytest.mark.ftr("FTR-FORMULA-FK-HELPER-PROVIDERS-P4A")
    def test_formula_mode_writes_structured_lookup_formula_specs(self):
        out = enrich_helpers(_frames(), {**DEFAULTS, "helper_value_mode": "formula"})

        helper_col = [
            c for c in out["A"].columns
            if (c[0] if isinstance(c, tuple) else c) == "_B_name"
        ][0]
        values = out["A"][helper_col].tolist()

        assert values == [
            LookupFormulaSpec(
                source_key_column="id_(B)",
                lookup_sheet="B",
                lookup_key_column="id",
                lookup_value_column="name",
                missing="",
            ),
            LookupFormulaSpec(
                source_key_column="id_(B)",
                lookup_sheet="B",
                lookup_key_column="id",
                lookup_value_column="name",
                missing="",
            ),
        ]
        assert not isinstance(values[0], str)

    @pytest.mark.ftr("FTR-FORMULA-FK-HELPER-PROVIDERS-P4A")
    def test_rejects_unknown_helper_value_mode(self):
        with pytest.raises(ValueError, match="helper_value_mode"):
            enrich_helpers(_frames(), {**DEFAULTS, "helper_value_mode": "backend_formula"})


# ---------------------------------------------------------------------------
# drop_helpers
# ---------------------------------------------------------------------------

class TestDropHelpers:

    def test_removes_helper_columns_via_provenance(self):
        enriched = enrich_helpers(_frames(), DEFAULTS)
        out = drop_helpers(enriched, prefix="_")
        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert "_B_name" not in cols_a
        assert "id" in cols_a

    def test_provenance_cleaned_up_after_drop(self):
        enriched = enrich_helpers(_frames(), DEFAULTS)
        out = drop_helpers(enriched, prefix="_")
        meta = out.get("_meta", {})
        derived = meta.get("derived", {})
        sheets = derived.get("sheets", {})
        for sheet_info in sheets.values():
            assert "helper_columns" not in sheet_info

    def test_prefix_fallback_without_provenance(self):
        frames = {
            "A": pd.DataFrame(
                {"id": [10], "id_(B)": [1], "_B_name": ["alpha"], "_custom": ["z"]}
            ),
            "B": pd.DataFrame({"id": [1], "name": ["alpha"]}),
        }
        out = drop_helpers(frames, prefix="_")
        cols_a = list(out["A"].columns)
        assert "_B_name" not in cols_a
        assert "_custom" not in cols_a
        assert "id" in cols_a

    def test_non_helper_underscored_column_kept_with_provenance(self):
        enriched = enrich_helpers(_frames(), DEFAULTS)
        enriched["A"][("_custom_field",) + ("",) * 2] = ["x", "y"]
        out = drop_helpers(enriched, prefix="_")
        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert "_B_name" not in cols_a
        assert "_custom_field" in cols_a

    def test_roundtrip_restores_original_columns(self):
        original = _frames()
        enriched = enrich_helpers(original, DEFAULTS)
        cleaned = drop_helpers(enriched, prefix="_")
        cols_a = [c[0] if isinstance(c, tuple) else c for c in cleaned["A"].columns]
        assert cols_a == ["id", "id_(B)"]
