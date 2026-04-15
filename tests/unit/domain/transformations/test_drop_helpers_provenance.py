"""FTR-FK-HELPER-PROVENANCE-CLEANUP: drop_helpers prefers metadata over prefix."""
from __future__ import annotations

import pytest
import pandas as pd

from spreadsheet_handling.pipeline.steps import make_apply_fks_step, make_drop_helpers_step

pytestmark = pytest.mark.ftr("FTR-FK-HELPER-PROVENANCE-CLEANUP")

DEFAULTS = {"id_field": "id", "label_field": "name", "helper_prefix": "_"}


def _enriched_frames(*, defaults=None):
    """Apply FK helpers and return frames with provenance."""
    defaults = defaults or DEFAULTS
    frames = {
        "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
        "B": pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]}),
    }
    step = make_apply_fks_step(defaults=defaults)
    return step.fn(frames)


class TestDropHelpersWithProvenance:

    def test_removes_helper_columns_via_provenance(self):
        enriched = _enriched_frames()
        step = make_drop_helpers_step(prefix="_")
        out = step.fn(enriched)

        cols_a = list(out["A"].columns)
        assert all("_B_name" not in str(c) for c in cols_a)
        assert "id" in [c[0] if isinstance(c, tuple) else c for c in cols_a]

    def test_provenance_cleaned_up_after_drop(self):
        enriched = _enriched_frames()
        step = make_drop_helpers_step(prefix="_")
        out = step.fn(enriched)

        meta = out.get("_meta", {})
        derived = meta.get("derived", {})
        # Either derived.sheets is gone entirely or has no helper_columns
        sheets = derived.get("sheets", {})
        for sheet_info in sheets.values():
            assert "helper_columns" not in sheet_info

    def test_multiple_helpers_removed_via_provenance(self):
        defaults = {
            **DEFAULTS,
            "helper_fields_by_fk": {"id_(B)": ["name"]},
        }
        frames = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame(
                {"id": [1, 2], "name": ["alpha", "beta"], "category": ["x", "y"]}
            ),
        }
        defaults_multi = {
            **DEFAULTS,
            "helper_fields_by_fk": {"id_(B)": ["category", "name"]},
        }
        enriched = make_apply_fks_step(defaults=defaults_multi).fn(frames)
        out = make_drop_helpers_step(prefix="_").fn(enriched)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert "_B_category" not in cols_a
        assert "_B_name" not in cols_a
        assert "id_(B)" in cols_a

    def test_non_helper_underscored_column_kept_with_provenance(self):
        """Provenance-based cleanup only removes listed columns, not all '_' columns."""
        enriched = _enriched_frames()
        # Add a non-helper column that starts with '_'
        enriched["A"][("_custom_field",) + ("",) * 2] = ["x", "y"]

        step = make_drop_helpers_step(prefix="_")
        out = step.fn(enriched)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        # _B_name removed (in provenance), but _custom_field kept (not in provenance)
        assert "_B_name" not in cols_a
        assert "_custom_field" in cols_a


class TestDropHelpersFallback:

    def test_prefix_fallback_without_provenance(self):
        """Without provenance metadata, drop_helpers still works via prefix."""
        frames = {
            "A": pd.DataFrame(
                {"id": [10], "id_(B)": [1], "_B_name": ["alpha"], "_custom": ["z"]}
            ),
            "B": pd.DataFrame({"id": [1], "name": ["alpha"]}),
        }
        step = make_drop_helpers_step(prefix="_")
        out = step.fn(frames)

        cols_a = list(out["A"].columns)
        assert "_B_name" not in cols_a
        assert "_custom" not in cols_a  # prefix removes ALL underscore cols
        assert "id" in cols_a

    def test_fallback_does_not_touch_meta(self):
        """Without provenance, _meta is untouched."""
        frames = {
            "A": pd.DataFrame({"id": [10], "_helper": ["x"]}),
            "_meta": {"version": "3.0"},
        }
        step = make_drop_helpers_step(prefix="_")
        out = step.fn(frames)

        assert out["_meta"] == {"version": "3.0"}


class TestDropHelpersRoundtrip:

    def test_apply_then_drop_roundtrip(self):
        """Full apply → drop roundtrip restores original columns."""
        original = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]}),
        }
        enriched = make_apply_fks_step(defaults=DEFAULTS).fn(original)
        cleaned = make_drop_helpers_step(prefix="_").fn(enriched)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in cleaned["A"].columns]
        assert cols_a == ["id", "id_(B)"]
