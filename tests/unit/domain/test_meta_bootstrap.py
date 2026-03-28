"""Tests for FTR-META-BOOTSTRAP: bootstrap_meta step and fault-tolerance."""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.meta_bootstrap import bootstrap_meta, _deep_merge
from spreadsheet_handling.pipeline.pipeline import make_bootstrap_meta_step, REGISTRY, build_steps_from_config
from spreadsheet_handling.rendering.ir import SheetIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MetaFrames(dict):
    """Dict-like frames that can carry a .meta attribute."""
    pass


def _plain_frames(**meta_kw):
    """Return a plain dict of frames, optionally with _meta."""
    frames = {"Sheet1": pd.DataFrame({"a": [1]})}
    if meta_kw:
        frames["_meta"] = dict(meta_kw)
    return frames


def _attr_frames(**meta_kw):
    """Return a MetaFrames instance with .meta attribute."""
    f = MetaFrames({"Sheet1": pd.DataFrame({"a": [1]})})
    f.meta = dict(meta_kw) if meta_kw else None
    return f


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------

class TestDeepMerge:
    def test_empty_base(self):
        assert _deep_merge({}, {"a": 1}) == {"a": 1}

    def test_empty_overlay(self):
        assert _deep_merge({"a": 1}, {}) == {"a": 1}

    def test_scalar_overwrite(self):
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_merge(self):
        base = {"style": {"header_fill_rgb": "#F2F2F2", "bold": True}}
        overlay = {"style": {"header_fill_rgb": "#00FF00"}}
        result = _deep_merge(base, overlay)
        assert result == {"style": {"header_fill_rgb": "#00FF00", "bold": True}}

    def test_list_replaces(self):
        assert _deep_merge({"a": [1]}, {"a": [2, 3]}) == {"a": [2, 3]}

    def test_disjoint_keys(self):
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_does_not_mutate_base(self):
        base = {"a": {"x": 1}}
        overlay = {"a": {"y": 2}}
        result = _deep_merge(base, overlay)
        assert "y" not in base["a"]
        assert result["a"] == {"x": 1, "y": 2}


# ---------------------------------------------------------------------------
# bootstrap_meta - dict-key interface (frames["_meta"])
# ---------------------------------------------------------------------------

class TestBootstrapMetaDictInterface:
    def test_missing_meta_becomes_empty(self):
        frames = {"Sheet1": pd.DataFrame({"a": [1]})}
        bootstrap_meta(frames)
        assert frames["_meta"] == {}

    def test_persisted_meta_preserved(self):
        frames = _plain_frames(version="1.0")
        bootstrap_meta(frames)
        assert frames["_meta"]["version"] == "1.0"

    def test_profile_defaults_applied(self):
        frames = _plain_frames()
        bootstrap_meta(frames, profile_defaults={"style": {"bold": True}})
        assert frames["_meta"]["style"]["bold"] is True

    def test_persisted_wins_over_profile(self):
        frames = _plain_frames(style={"bold": False})
        bootstrap_meta(frames, profile_defaults={"style": {"bold": True}})
        assert frames["_meta"]["style"]["bold"] is False

    def test_cli_overrides_win_over_persisted(self):
        frames = _plain_frames(style={"bold": True})
        bootstrap_meta(frames, cli_overrides={"style": {"bold": False}})
        assert frames["_meta"]["style"]["bold"] is False

    def test_full_precedence_chain(self):
        frames = _plain_frames(freeze_header=True)
        bootstrap_meta(
            frames,
            profile_defaults={"auto_filter": True, "freeze_header": False, "color": "red"},
            cli_overrides={"color": "blue"},
        )
        meta = frames["_meta"]
        assert meta["auto_filter"] is True       # profile (not in persisted)
        assert meta["freeze_header"] is True      # persisted wins over profile
        assert meta["color"] == "blue"            # CLI wins over everything


# ---------------------------------------------------------------------------
# bootstrap_meta - attribute interface (frames.meta)
# ---------------------------------------------------------------------------

class TestBootstrapMetaAttrInterface:
    def test_none_meta_becomes_empty(self):
        frames = _attr_frames()  # meta=None
        bootstrap_meta(frames)
        assert frames.meta == {}

    def test_profile_defaults_via_attr(self):
        frames = _attr_frames()
        bootstrap_meta(frames, profile_defaults={"auto_filter": True})
        assert frames.meta["auto_filter"] is True

    def test_persisted_wins_via_attr(self):
        frames = _attr_frames(auto_filter=False)
        bootstrap_meta(frames, profile_defaults={"auto_filter": True})
        assert frames.meta["auto_filter"] is False

    def test_cli_wins_via_attr(self):
        frames = _attr_frames(auto_filter=False)
        bootstrap_meta(frames, cli_overrides={"auto_filter": True})
        assert frames.meta["auto_filter"] is True


# ---------------------------------------------------------------------------
# Pipeline step factory
# ---------------------------------------------------------------------------

class TestBootstrapMetaStep:
    def test_registered_in_registry(self):
        assert "bootstrap_meta" in REGISTRY

    def test_factory_creates_bound_step(self):
        step = make_bootstrap_meta_step()
        assert step.name == "bootstrap_meta"

    def test_step_callable_in_pipeline(self):
        step = make_bootstrap_meta_step(
            profile_defaults={"auto_filter": True},
        )
        frames = _plain_frames()
        result = step(frames)
        assert result["_meta"]["auto_filter"] is True

    def test_build_from_config_spec(self):
        specs = [
            {"step": "bootstrap_meta", "profile_defaults": {"freeze_header": True}}
        ]
        steps = build_steps_from_config(specs)
        assert len(steps) == 1
        assert steps[0].name == "bootstrap_meta"


# ---------------------------------------------------------------------------
# SheetIR fault tolerance
# ---------------------------------------------------------------------------

class TestSheetIRMetaFaultTolerance:
    def test_meta_defaults_to_dict(self):
        ir = SheetIR(name="test")
        assert ir.meta == {}

    def test_none_meta_coerced_to_dict(self):
        ir = SheetIR(name="test", meta=None)
        assert ir.meta == {}
        # Must be usable immediately
        ir.meta["key"] = "value"
        assert ir.meta["key"] == "value"


# ---------------------------------------------------------------------------
# Nested-merge semantics (step-local append pattern)
# ---------------------------------------------------------------------------

class TestStepLocalMergePattern:
    """Verify that step-local code can use _deep_merge to append lists."""

    def test_helper_list_replacement(self):
        """Per spec: lists replace (append is step-local logic, not _deep_merge)."""
        base = {"non_essential": ["_col1"]}
        overlay = {"non_essential": ["_col1", "_col2"]}
        result = _deep_merge(base, overlay)
        assert result["non_essential"] == ["_col1", "_col2"]

    def test_step_can_append_via_explicit_code(self):
        """Show the intended pattern: step reads, appends, writes."""
        frames = _plain_frames(non_essential=["_col1"])
        bootstrap_meta(frames)
        meta = frames["_meta"]
        # Simulate a later step appending
        meta["non_essential"] = list(meta.get("non_essential", [])) + ["_col2"]
        assert meta["non_essential"] == ["_col1", "_col2"]
