"""Validate-step mode tests: duplicate_ids fail, missing_fk warn/fail.

Migrated from legacy_pre_hex (test_validate_duplicates, test_validate_missing_fk).
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.pipeline import (
    make_validate_step,
    run_pipeline,
)


def _frames_with_duplicate_ids():
    return {"A": pd.DataFrame([{"id": 1, "name": "Alpha"}, {"id": 1, "name": "Beta"}])}


def _frames_with_missing_fk():
    return {
        "A": pd.DataFrame([{"id": 1, "name": "Alpha"}]),
        "B": pd.DataFrame([{"id_(A)": 1}, {"id_(A)": 99}]),  # 99 does not exist in A
    }


DEFAULTS = {
    "id_field": "id",
    "label_field": "name",
    "helper_prefix": "_",
    "detect_fk": True,
    "levels": 3,
}


@pytest.mark.ftr("FTR-PREHEX-TEST-CONSOLIDATION-P3C")
class TestDuplicateIdsFail:
    def test_raises_on_fail_mode(self):
        frames = _frames_with_duplicate_ids()
        step = make_validate_step(
            defaults=DEFAULTS, mode_duplicate_ids="fail", mode_missing_fk="ignore",
        )
        with pytest.raises(ValueError, match="(?i)duplicate"):
            run_pipeline(frames, [step])

    def test_warn_mode_does_not_raise(self):
        frames = _frames_with_duplicate_ids()
        step = make_validate_step(
            defaults=DEFAULTS, mode_duplicate_ids="warn", mode_missing_fk="ignore",
        )
        out = run_pipeline(frames, [step])
        assert "A" in out


@pytest.mark.ftr("FTR-PREHEX-TEST-CONSOLIDATION-P3C")
class TestMissingFkModes:
    def test_warn_does_not_raise(self):
        frames = _frames_with_missing_fk()
        step = make_validate_step(
            defaults=DEFAULTS, mode_missing_fk="warn", mode_duplicate_ids="ignore",
        )
        out = run_pipeline(frames, [step])
        assert "A" in out and "B" in out

    def test_fail_raises(self):
        frames = _frames_with_missing_fk()
        step = make_validate_step(
            defaults=DEFAULTS, mode_missing_fk="fail", mode_duplicate_ids="ignore",
        )
        with pytest.raises(ValueError, match="(?i)unresolvable"):
            run_pipeline(frames, [step])

    def test_ignore_is_silent(self):
        frames = _frames_with_missing_fk()
        step = make_validate_step(
            defaults=DEFAULTS, mode_missing_fk="ignore", mode_duplicate_ids="ignore",
        )
        out = run_pipeline(frames, [step])
        assert "B" in out


@pytest.mark.ftr("FTR-PREHEX-TEST-CONSOLIDATION-P3C")
class TestDetectFkToggle:
    def test_detect_fk_disabled_skips_helper(self):
        frames = {
            "Ziel": pd.DataFrame([{"id": 1, "name": "Alpha"}]),
            "Q": pd.DataFrame([{"id_(Ziel)": 1}]),
        }
        from spreadsheet_handling.pipeline.pipeline import make_apply_fks_step
        step = make_apply_fks_step(defaults={**DEFAULTS, "detect_fk": False})
        out = run_pipeline(frames, [step])
        # no helper columns should have been added
        assert all(not str(c).startswith("_") for c in out["Q"].columns)
