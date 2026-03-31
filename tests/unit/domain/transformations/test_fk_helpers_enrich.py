"""Tests for FK-helper enrichment as pure domain transformation."""
from __future__ import annotations

import pytest
import pandas as pd

from spreadsheet_handling.core.fk import (
    build_registry,
    build_id_label_maps,
    detect_fk_columns,
    apply_fk_helpers,
)

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
