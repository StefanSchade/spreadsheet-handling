"""FTR-FK-HELPER-PROVENANCE-CLEANUP: drop_helpers prefers metadata over prefix.

FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5 removed the prefix fallback that
previously served as the no-policy path; ``remove_fk_helpers`` now requires
either derived helper provenance or v2 relation policy. Tests in this module
seed v2 policy via ``infer_fk_relations`` before invoking ``add_fk_helpers``.
"""
from __future__ import annotations

import pytest
import pandas as pd

from spreadsheet_handling.domain.fk_relations import infer_fk_relations
from spreadsheet_handling.domain.helper_policies import configure_fk_helpers
from spreadsheet_handling.pipeline.steps import make_apply_fks_step, make_drop_helpers_step

pytestmark = pytest.mark.ftr("FTR-FK-HELPER-PROVENANCE-CLEANUP")

DEFAULTS = {"id_field": "id", "label_field": "name", "helper_prefix": "_"}


def _enriched_frames(*, defaults=None):
    """Apply FK helpers and return frames with provenance."""
    defaults = defaults or DEFAULTS
    frames = infer_fk_relations({
        "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
        "B": pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]}),
    })
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
        sheets = derived.get("sheets", {})
        for sheet_info in sheets.values():
            assert "helper_columns" not in sheet_info

    def test_multiple_helpers_removed_via_provenance(self):
        frames = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame(
                {"id": [1, 2], "name": ["alpha", "beta"], "category": ["x", "y"]}
            ),
        }
        configured = configure_fk_helpers(
            frames,
            target="B",
            key="id",
            allowed_helpers=["category", "name"],
            default_helpers=["category", "name"],
        )
        enriched = make_apply_fks_step(defaults=DEFAULTS).fn(configured)
        out = make_drop_helpers_step(prefix="_").fn(enriched)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert "_B_category" not in cols_a
        assert "_B_name" not in cols_a
        assert "id_(B)" in cols_a

    def test_non_helper_underscored_column_kept_with_provenance(self):
        """Provenance-based cleanup only removes listed columns, not all '_' columns."""
        enriched = _enriched_frames()
        enriched["A"][("_custom_field",) + ("",) * 2] = ["x", "y"]

        step = make_drop_helpers_step(prefix="_")
        out = step.fn(enriched)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        # _B_name removed (in provenance), but _custom_field kept (not in provenance)
        assert "_B_name" not in cols_a
        assert "_custom_field" in cols_a


class TestDropHelpersRequiresPolicy:

    def test_no_policy_and_no_provenance_raises_with_actionable_message(self):
        """Without provenance or v2 policy, drop_helpers fails clearly."""
        frames = {
            "A": pd.DataFrame(
                {"id": [10], "id_(B)": [1], "_B_name": ["alpha"], "_custom": ["z"]}
            ),
            "B": pd.DataFrame({"id": [1], "name": ["alpha"]}),
        }
        step = make_drop_helpers_step(prefix="_")
        with pytest.raises(ValueError, match="infer_fk_relations"):
            step.fn(frames)

    def test_drop_removes_columns_from_v2_policy_when_provenance_missing(self):
        """When only v2 policy is present (no per-sheet provenance), the
        declared helper columns are still removed; this is the post-reimport
        cleanup path."""
        frames = infer_fk_relations({
            "A": pd.DataFrame(
                {"id": [10, 20], "id_(B)": [1, 2], "_B_name": ["alpha", "beta"]}
            ),
            "B": pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]}),
        })
        # No derived.sheets provenance was written.
        assert "derived" not in (frames.get("_meta") or {})

        step = make_drop_helpers_step(prefix="_")
        out = step.fn(frames)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert "_B_name" not in cols_a
        assert "id_(B)" in cols_a


class TestDropHelpersRoundtrip:

    def test_apply_then_drop_roundtrip(self):
        """Full apply → drop roundtrip restores original columns."""
        original = infer_fk_relations({
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]}),
        })
        enriched = make_apply_fks_step(defaults=DEFAULTS).fn(original)
        cleaned = make_drop_helpers_step(prefix="_").fn(enriched)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in cleaned["A"].columns]
        assert cols_a == ["id", "id_(B)"]
