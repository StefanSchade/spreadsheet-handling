"""Tests for FK-helper enrichment as pure domain transformation."""
from __future__ import annotations

import pytest
import pandas as pd

from spreadsheet_handling.core.fk import (
    build_registry,
    build_id_label_maps,
    build_id_value_maps,
    detect_fk_columns,
    apply_fk_helpers,
)
from spreadsheet_handling.core.indexing import level0_series
from spreadsheet_handling.pipeline.steps import make_apply_fks_step

pytestmark = pytest.mark.ftr("FTR-FK-HELPER-REFACTOR-P3B")

DEFAULTS = {"id_field": "id", "label_field": "name", "helper_prefix": "_"}


def _frames():
    b = pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]})
    a = pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]})
    return {"A": a, "B": b}


class TestApplyFkHelpers:

    def test_adds_helper_column(self):
        frames = _frames()
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        result = apply_fk_helpers(frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_")
        assert "_B_name" in [c[0] if isinstance(c, tuple) else c for c in result.columns]

    def test_helper_values_match_lookup(self):
        frames = _frames()
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        result = apply_fk_helpers(frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_")
        # Helper column is stored as tuple even at levels=1
        helper_col = [c for c in result.columns if (c[0] if isinstance(c, tuple) else c) == "_B_name"][0]
        helpers = result[helper_col].tolist()
        assert helpers == ["alpha", "beta"]

    def test_no_fk_columns_returns_unchanged(self):
        df = pd.DataFrame({"id": [1], "value": ["x"]})
        reg = build_registry({"X": df}, DEFAULTS)
        id_maps = build_id_label_maps({"X": df}, reg)
        fk_defs = detect_fk_columns(df, reg, helper_prefix="_")
        assert fk_defs == []
        result = apply_fk_helpers(df, fk_defs, id_maps, levels=1)
        assert list(result.columns) == ["id", "value"]

    def test_detect_fk_disabled_skips(self):
        frames = _frames()
        reg = build_registry(frames, DEFAULTS)
        # Empty registry simulates detect_fk=False (no target sheets matched)
        fk_defs = detect_fk_columns(frames["A"], {}, helper_prefix="_")
        assert fk_defs == []

    def test_adds_multiple_helper_columns_in_configured_order(self):
        frames = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame(
                {
                    "id": [1, 2],
                    "name": ["alpha", "beta"],
                    "category": ["x", "y"],
                }
            ),
        }
        defaults = {
            **DEFAULTS,
            "helper_fields_by_fk": {"id_(B)": ["category", "name"]},
        }
        reg = build_registry(frames, defaults)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_", defaults=defaults)
        id_maps = build_id_value_maps(frames, reg, fields_by_sheet={"B": ["category", "name"]})

        result = apply_fk_helpers(frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_")
        lvl0 = [c[0] if isinstance(c, tuple) else c for c in result.columns]

        assert lvl0 == ["id", "id_(B)", "_B_category", "_B_name"]
        assert level0_series(result, "_B_category").tolist() == ["x", "y"]
        assert level0_series(result, "_B_name").tolist() == ["alpha", "beta"]


class TestApplyFksStepProvenance:
    """FTR-FK-HELPER-PROVENANCE-CLEANUP: apply_fks writes derived provenance."""

    def test_provenance_written_for_single_helper(self):
        frames = _frames()
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        meta = out["_meta"]
        prov = meta["derived"]["sheets"]["A"]["helper_columns"]
        assert len(prov) == 1
        assert prov[0] == {
            "column": "_B_name",
            "fk_column": "id_(B)",
            "target": "B",
            "value_field": "name",
        }

    def test_provenance_written_for_multiple_helpers_in_order(self):
        frames = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame(
                {"id": [1, 2], "name": ["alpha", "beta"], "category": ["x", "y"]}
            ),
        }
        defaults = {
            **DEFAULTS,
            "helper_fields_by_fk": {"id_(B)": ["category", "name"]},
        }
        step = make_apply_fks_step(defaults=defaults)
        out = step.fn(frames)

        prov = out["_meta"]["derived"]["sheets"]["A"]["helper_columns"]
        assert len(prov) == 2
        assert prov[0]["column"] == "_B_category"
        assert prov[1]["column"] == "_B_name"
        assert prov[0]["value_field"] == "category"
        assert prov[1]["value_field"] == "name"

    def test_no_provenance_for_sheet_without_fks(self):
        frames = _frames()
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        derived_sheets = out["_meta"]["derived"]["sheets"]
        assert "B" not in derived_sheets

    def test_provenance_preserves_existing_meta(self):
        frames = _frames()
        frames["_meta"] = {"version": "3.0", "author": "test"}
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        assert out["_meta"]["version"] == "3.0"
        assert out["_meta"]["author"] == "test"
        assert "derived" in out["_meta"]

    def test_stale_provenance_removed_for_sheet_without_current_fks(self):
        """apply_fks removes stale helper_columns provenance for sheets that
        no longer have FK defs in the current run."""
        frames = _frames()
        # Inject stale provenance for a sheet that has no FKs
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
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        derived_sheets = out["_meta"]["derived"]["sheets"]
        assert "B" not in derived_sheets
        assert "A" in derived_sheets

    def test_stale_provenance_removed_for_sheet_no_longer_in_frames(self):
        """apply_fks cleans provenance for sheets that are not in frames at all."""
        frames = _frames()
        frames["_meta"] = {
            "derived": {
                "sheets": {
                    "Gone": {
                        "helper_columns": [
                            {"column": "_Z_val", "fk_column": "id_(Z)",
                             "target": "Z", "value_field": "val"},
                        ]
                    }
                }
            }
        }
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        derived_sheets = out["_meta"]["derived"]["sheets"]
        assert "Gone" not in derived_sheets

    def test_key_selective_merge_preserves_other_derived_keys(self):
        """apply_fks only replaces helper_columns, not the whole sheet dict."""
        frames = _frames()
        frames["_meta"] = {
            "derived": {
                "sheets": {
                    "A": {"other_derived_key": "keep_me"}
                }
            }
        }
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        sheet_derived = out["_meta"]["derived"]["sheets"]["A"]
        assert sheet_derived["other_derived_key"] == "keep_me"
        assert "helper_columns" in sheet_derived
