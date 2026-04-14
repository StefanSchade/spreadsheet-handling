"""FK-helper edge cases: custom id_field, mixed types, multi-targets, missing label, duplicate-ids last-wins.

Migrated from legacy_pre_hex (test_fk_custom_id_field, test_fk_mixed_types,
test_fk_multi_targets, test_fk_missing_label_field, test_fk_duplicate_ids).
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.fk import (
    build_registry,
    build_id_label_maps,
    detect_fk_columns,
    apply_fk_helpers,
    assert_no_parentheses_in_columns,
)
from spreadsheet_handling.core.indexing import level0_series
from spreadsheet_handling.pipeline.pipeline import (
    make_apply_fks_step,
    make_reorder_helpers_step,
    run_pipeline,
)


@pytest.mark.ftr("FTR-PREHEX-TEST-CONSOLIDATION-P3C")
class TestCustomIdField:
    def test_fk_with_custom_id_field(self):
        frames = {
            "Guten Morgen": pd.DataFrame(
                [{"Schluessel": "A-1", "name": "Alpha"}, {"Schluessel": "B-2", "name": "Beta"}]
            ),
            "Bestellungen": pd.DataFrame(
                [{"bestellnr": "B-1", "Schluessel_(Guten_Morgen)": "A-1"},
                 {"bestellnr": "B-2", "Schluessel_(Guten_Morgen)": "B-2"}]
            ),
        }
        defaults = {"id_field": "Schluessel", "label_field": "name",
                     "helper_prefix": "_", "detect_fk": True, "levels": 3}
        step = make_apply_fks_step(defaults=defaults)
        out = run_pipeline(frames, [step])

        dfq = out["Bestellungen"]
        lvl0 = [c[0] if isinstance(c, tuple) else c for c in dfq.columns]
        helper_cols = [c for c in lvl0 if str(c).startswith("_")]
        assert helper_cols, f"no helper column in {lvl0}"
        s = level0_series(dfq, helper_cols[0])
        assert list(s) == ["Alpha", "Beta"]


@pytest.mark.ftr("FTR-PREHEX-TEST-CONSOLIDATION-P3C")
class TestMixedIdTypes:
    def test_mixed_int_string_fk_match(self):
        frames = {
            "Ziel": pd.DataFrame([{"id": "1", "name": "Alpha"}]),
            "Q": pd.DataFrame([{"id_(Ziel)": 1}]),  # int FK referencing string id
        }
        defaults = {"id_field": "id", "label_field": "name",
                     "helper_prefix": "_", "detect_fk": True, "levels": 3}
        step = make_apply_fks_step(defaults=defaults)
        out = run_pipeline(frames, [step])

        dfq = out["Q"]
        lvl0 = [c[0] if isinstance(c, tuple) else c for c in dfq.columns]
        helper_cols = [c for c in lvl0 if str(c).startswith("_")]
        assert helper_cols
        s = level0_series(dfq, helper_cols[0])
        assert list(s) == ["Alpha"]


@pytest.mark.ftr("FTR-PREHEX-TEST-CONSOLIDATION-P3C")
class TestMultiFkTargets:
    def test_multiple_fk_helpers(self):
        frames = {
            "Orte": pd.DataFrame([{"id": 1, "name": "Insel"}, {"id": 2, "name": "Berg"}]),
            "Kunden": pd.DataFrame([{"id": "A", "name": "Anna"}, {"id": "B", "name": "Bob"}]),
            "Buchungen": pd.DataFrame([
                {"nr": 1, "id_(Orte)": 1, "id_(Kunden)": "A"},
                {"nr": 2, "id_(Orte)": 2, "id_(Kunden)": "B"},
            ]),
        }
        defaults = {"id_field": "id", "label_field": "name",
                     "helper_prefix": "_", "detect_fk": True, "levels": 3}
        step = make_apply_fks_step(defaults=defaults)
        out = run_pipeline(frames, [step])

        dfq = out["Buchungen"]
        lvl0 = [c[0] if isinstance(c, tuple) else c for c in dfq.columns]
        helper_cols = sorted(c for c in lvl0 if str(c).startswith("_"))
        assert len(helper_cols) >= 2, f"expected >=2 helper cols, got {helper_cols}"
        orte_helper = [c for c in helper_cols if "Orte" in str(c)]
        kunden_helper = [c for c in helper_cols if "Kunden" in str(c)]
        assert orte_helper and kunden_helper
        assert list(level0_series(dfq, orte_helper[0])) == ["Insel", "Berg"]
        assert list(level0_series(dfq, kunden_helper[0])) == ["Anna", "Bob"]

    def test_reorder_helpers_respects_configured_helper_order(self):
        frames = {
            "B": pd.DataFrame(
                [
                    {"id": 1, "name": "Alpha", "category": "A"},
                    {"id": 2, "name": "Beta", "category": "B"},
                ]
            ),
            "A": pd.DataFrame(
                [
                    {"id": 10, "other": "x", "id_(B)": 1},
                    {"id": 20, "other": "y", "id_(B)": 2},
                ]
            ),
        }
        defaults = {
            "id_field": "id",
            "label_field": "name",
            "helper_prefix": "_",
            "detect_fk": True,
            "levels": 3,
            "helper_fields_by_fk": {"id_(B)": ["category", "name"]},
        }

        out = run_pipeline(
            frames,
            [
                make_apply_fks_step(defaults=defaults),
                make_reorder_helpers_step(helper_prefix="_"),
            ],
        )

        lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert lvl0 == ["id", "other", "id_(B)", "_B_category", "_B_name"]


@pytest.mark.ftr("FTR-PREHEX-TEST-CONSOLIDATION-P3C")
class TestMissingLabelField:
    def test_missing_label_field_results_in_none_helper(self):
        frames = {
            "Ziel": pd.DataFrame([{"id": 1}, {"id": 2}]),  # no "name" column
            "Quelle": pd.DataFrame([{"fk": "x", "id_(Ziel)": 1}]),
        }
        defaults = {"id_field": "id", "label_field": "name",
                     "helper_prefix": "_", "detect_fk": True, "levels": 3}
        step = make_apply_fks_step(defaults=defaults)
        out = run_pipeline(frames, [step])

        dfq = out["Quelle"]
        lvl0 = [c[0] if isinstance(c, tuple) else c for c in dfq.columns]
        helper_cols = [c for c in lvl0 if str(c).startswith("_")]
        assert helper_cols, f"expected helper column, got {lvl0}"
        s = level0_series(dfq, helper_cols[0])
        assert pd.isna(s.iloc[0])


@pytest.mark.ftr("FTR-PREHEX-TEST-CONSOLIDATION-P3C")
class TestDuplicateIdsLastWins:
    def test_duplicate_ids_last_one_wins(self):
        """When a target sheet has duplicate IDs, the last label wins in the id-label map."""
        frames = {
            "Ziel": pd.DataFrame([{"id": 1, "name": "Alt"}, {"id": 1, "name": "Neu"}]),
            "Q": pd.DataFrame([{"id_(Ziel)": 1}]),
        }
        defaults = {"id_field": "id", "label_field": "name",
                     "helper_prefix": "_", "detect_fk": True, "levels": 3}
        step = make_apply_fks_step(defaults=defaults)
        out = run_pipeline(frames, [step])

        dfq = out["Q"]
        lvl0 = [c[0] if isinstance(c, tuple) else c for c in dfq.columns]
        helper_cols = [c for c in lvl0 if str(c).startswith("_")]
        assert helper_cols
        s = level0_series(dfq, helper_cols[0])
        assert list(s) == ["Neu"]


@pytest.mark.ftr("FTR-PREHEX-TEST-CONSOLIDATION-P3C")
class TestParenthesesGuard:
    def test_parentheses_in_non_fk_column_rejected(self):
        df = pd.DataFrame({"x(y)": [1], "id_(Ziel)": [1]})
        with pytest.raises(ValueError, match="nicht erlaubt"):
            assert_no_parentheses_in_columns(df, "Bestellungen")

    def test_fk_column_parentheses_allowed(self):
        df = pd.DataFrame({"id_(Ziel)": [1], "normal": [2]})
        # should not raise
        assert_no_parentheses_in_columns(df, "Bestellungen")
