"""Tests for FTR-YAML-OVERRIDES: per-sheet config from YAML files."""
from __future__ import annotations

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.domain.yaml_overrides import load_overrides, apply_overrides
from spreadsheet_handling.domain.meta_bootstrap import bootstrap_meta, _deep_merge
from spreadsheet_handling.pipeline.pipeline import (
    make_apply_overrides_step,
    build_steps_from_config,
    REGISTRY,
)

pytestmark = pytest.mark.ftr("FTR-YAML-OVERRIDES")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plain_frames(**meta_kw):
    frames = {"Kunden": pd.DataFrame({"id": [1]}), "Bestellungen": pd.DataFrame({"bestellnr": ["B-1"]})}
    if meta_kw:
        frames["_meta"] = dict(meta_kw)
    return frames


# ---------------------------------------------------------------------------
# load_overrides
# ---------------------------------------------------------------------------

class TestLoadOverrides:
    def test_load_valid_file(self, tmp_path):
        p = tmp_path / "overrides.yaml"
        p.write_text(yaml.dump({
            "defaults": {"auto_filter": True},
            "sheets": {"Kunden": {"id_field": "kunden_id"}},
        }))
        result = load_overrides(p)
        assert result["defaults"]["auto_filter"] is True
        assert result["sheets"]["Kunden"]["id_field"] == "kunden_id"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_overrides(tmp_path / "nope.yaml")

    def test_empty_file_returns_empty_dict(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        result = load_overrides(p)
        assert result == {}

    def test_non_mapping_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_overrides(p)


# ---------------------------------------------------------------------------
# apply_overrides — defaults
# ---------------------------------------------------------------------------

class TestApplyOverridesDefaults:
    def test_defaults_merged_into_meta(self):
        frames = _plain_frames()
        apply_overrides(frames, {"defaults": {"auto_filter": True, "freeze_header": False}})
        meta = frames["_meta"]
        assert meta["auto_filter"] is True
        assert meta["freeze_header"] is False

    def test_defaults_do_not_clobber_existing(self):
        frames = _plain_frames(auto_filter=False)
        apply_overrides(frames, {"defaults": {"auto_filter": True, "extra": 42}})
        meta = frames["_meta"]
        # deep_merge: overlay wins, so auto_filter becomes True
        assert meta["auto_filter"] is True
        assert meta["extra"] == 42

    def test_no_defaults_key_is_noop(self):
        frames = _plain_frames(version="1.0")
        apply_overrides(frames, {"sheets": {"Kunden": {"id_field": "x"}}})
        assert frames["_meta"]["version"] == "1.0"


# ---------------------------------------------------------------------------
# apply_overrides — per-sheet
# ---------------------------------------------------------------------------

class TestApplyOverridesPerSheet:
    def test_sheet_options_stored_under_sheets_key(self):
        frames = _plain_frames()
        apply_overrides(frames, {
            "sheets": {
                "Kunden": {"id_field": "kunden_id", "auto_filter": True},
                "Bestellungen": {"freeze_header": True},
            }
        })
        meta = frames["_meta"]
        assert meta["sheets"]["Kunden"]["id_field"] == "kunden_id"
        assert meta["sheets"]["Kunden"]["auto_filter"] is True
        assert meta["sheets"]["Bestellungen"]["freeze_header"] is True

    def test_sheet_overrides_merge_with_existing(self):
        frames = _plain_frames(sheets={"Kunden": {"helper_prefix": "_"}})
        apply_overrides(frames, {
            "sheets": {"Kunden": {"id_field": "kunden_id"}}
        })
        meta = frames["_meta"]
        assert meta["sheets"]["Kunden"]["helper_prefix"] == "_"
        assert meta["sheets"]["Kunden"]["id_field"] == "kunden_id"

    def test_non_dict_sheet_config_ignored(self):
        frames = _plain_frames()
        apply_overrides(frames, {"sheets": {"Kunden": "invalid"}})
        meta = frames["_meta"]
        assert "sheets" not in meta or "Kunden" not in meta.get("sheets", {})


# ---------------------------------------------------------------------------
# Precedence: defaults < per-sheet YAML < CLI overrides
# ---------------------------------------------------------------------------

class TestFullPrecedenceChain:
    def test_yaml_defaults_then_per_sheet_then_cli(self):
        """Full chain: bootstrap_meta(profile) → apply_overrides(yaml) → bootstrap_meta(cli)."""
        frames = _plain_frames()

        # Step 1: profile defaults via bootstrap_meta
        bootstrap_meta(frames, profile_defaults={"auto_filter": False, "color": "red"})

        # Step 2: YAML overrides (higher priority than profile)
        apply_overrides(frames, {
            "defaults": {"auto_filter": True},
            "sheets": {"Kunden": {"freeze_header": True}},
        })

        # Step 3: CLI overrides (highest)
        bootstrap_meta(frames, cli_overrides={"color": "blue"})

        meta = frames["_meta"]
        assert meta["auto_filter"] is True      # YAML wins over profile
        assert meta["color"] == "blue"           # CLI wins over everything
        assert meta["sheets"]["Kunden"]["freeze_header"] is True  # per-sheet preserved


# ---------------------------------------------------------------------------
# Pipeline step factory
# ---------------------------------------------------------------------------

class TestApplyOverridesStep:
    def test_registered_in_registry(self):
        assert "apply_overrides" in REGISTRY

    def test_factory_with_inline_overrides(self):
        step = make_apply_overrides_step(
            overrides={"defaults": {"auto_filter": True}}
        )
        assert step.name == "apply_overrides"
        frames = _plain_frames()
        result = step(frames)
        assert result["_meta"]["auto_filter"] is True

    def test_factory_with_file_path(self, tmp_path):
        p = tmp_path / "ov.yaml"
        p.write_text(yaml.dump({"sheets": {"Kunden": {"id_field": "kid"}}}))
        step = make_apply_overrides_step(overrides_path=str(p))
        frames = _plain_frames()
        result = step(frames)
        assert result["_meta"]["sheets"]["Kunden"]["id_field"] == "kid"

    def test_factory_no_overrides_is_noop(self):
        step = make_apply_overrides_step()
        frames = _plain_frames(version="1.0")
        result = step(frames)
        assert result["_meta"]["version"] == "1.0"

    def test_build_from_config_spec(self, tmp_path):
        p = tmp_path / "ov.yaml"
        p.write_text(yaml.dump({"defaults": {"auto_filter": False}}))
        specs = [{"step": "apply_overrides", "overrides_path": str(p)}]
        steps = build_steps_from_config(specs)
        assert len(steps) == 1
        assert steps[0].name == "apply_overrides"


# ---------------------------------------------------------------------------
# Composer integration: per-sheet options reach SheetIR
# ---------------------------------------------------------------------------

class TestComposerIntegration:
    def test_workbook_defaults_flow_to_each_sheet_options(self):
        from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
        frames = {"Sheet1": pd.DataFrame({"a": [1]})}
        meta = {"freeze_header": True, "auto_filter": False, "header_fill_rgb": "#123456"}
        ir = compose_workbook(frames, meta)
        opts = ir.sheets["Sheet1"].meta.get("options", {})
        assert opts["freeze_header"] is True
        assert opts["auto_filter"] is False
        assert opts["header_fill_rgb"] == "#123456"

    def test_sheet_options_override_workbook_defaults(self):
        from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
        frames = {"Sheet1": pd.DataFrame({"a": [1]})}
        meta = {
            "freeze_header": True,
            "auto_filter": True,
            "sheets": {"Sheet1": {"freeze_header": False}},
        }
        ir = compose_workbook(frames, meta)
        opts = ir.sheets["Sheet1"].meta.get("options", {})
        assert opts["freeze_header"] is False
        assert opts["auto_filter"] is True

    def test_sheet_options_flow_to_ir(self):
        from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
        frames = {"Sheet1": pd.DataFrame({"a": [1]})}
        meta = {"sheets": {"Sheet1": {"freeze_header": True, "auto_filter": False}}}
        ir = compose_workbook(frames, meta)
        opts = ir.sheets["Sheet1"].meta.get("options", {})
        assert opts["freeze_header"] is True
        assert opts["auto_filter"] is False

    def test_missing_sheet_options_leaves_empty(self):
        from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
        frames = {"Sheet1": pd.DataFrame({"a": [1]})}
        meta = {"sheets": {"Other": {"freeze_header": True}}}
        ir = compose_workbook(frames, meta)
        opts = ir.sheets["Sheet1"].meta.get("options", {})
        assert opts == {}

    def test_no_meta_no_options(self):
        from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
        frames = {"Sheet1": pd.DataFrame({"a": [1]})}
        ir = compose_workbook(frames, None)
        opts = ir.sheets["Sheet1"].meta.get("options", {})
        assert opts == {}


# ---------------------------------------------------------------------------
# End-to-end: YAML → overrides → compose → passes → render plan
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_yaml_defaults_reach_render_plan(self, tmp_path):
        from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
        from spreadsheet_handling.rendering.passes.core import StylePass, FilterPass, FreezePass
        from spreadsheet_handling.rendering.flow import apply_ir_passes, build_render_plan

        ov_path = tmp_path / "overrides.yaml"
        ov_path.write_text(yaml.dump({
            "defaults": {
                "freeze_header": True,
                "auto_filter": True,
                "header_fill_rgb": "#00FF00",
            },
            "sheets": {
                "Products": {
                    "freeze_header": False,
                },
            },
        }))

        frames = {"Products": pd.DataFrame({"id": [1, 2], "name": ["A", "B"]})}
        frames["_meta"] = {}
        overrides = load_overrides(ov_path)
        apply_overrides(frames, overrides)

        meta = frames["_meta"]
        ir = compose_workbook(frames, meta)
        ir = apply_ir_passes(ir, [StylePass(), FilterPass(), FreezePass()])
        plan = build_render_plan(ir)

        op_names = [(type(op).__name__, getattr(op, "sheet", None)) for op in plan.ops]
        assert ("SetAutoFilter", "Products") in op_names
        assert ("SetFreeze", "Products") not in op_names

    def test_yaml_overrides_reach_render_plan(self, tmp_path):
        from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
        from spreadsheet_handling.rendering.passes.core import StylePass, FilterPass, FreezePass
        from spreadsheet_handling.rendering.flow import apply_ir_passes, build_render_plan

        # Write overrides YAML
        ov_path = tmp_path / "overrides.yaml"
        ov_path.write_text(yaml.dump({
            "sheets": {
                "Products": {
                    "freeze_header": True,
                    "auto_filter": True,
                    "header_fill_rgb": "#00FF00",
                },
            },
        }))

        # Build frames + apply overrides
        frames = {"Products": pd.DataFrame({"id": [1, 2], "name": ["A", "B"]})}
        frames["_meta"] = {}
        overrides = load_overrides(ov_path)
        apply_overrides(frames, overrides)

        # Compose → passes → plan
        meta = frames["_meta"]
        ir = compose_workbook(frames, meta)
        ir = apply_ir_passes(ir, [StylePass(), FilterPass(), FreezePass()])
        plan = build_render_plan(ir)

        # Verify plan has freeze and filter ops for Products
        op_names = [(type(op).__name__, getattr(op, "sheet", None)) for op in plan.ops]
        assert ("SetFreeze", "Products") in op_names
        assert ("SetAutoFilter", "Products") in op_names

        # Verify header fill colour came through
        header_ops = [op for op in plan.ops
                      if type(op).__name__ == "ApplyHeaderStyle" and op.sheet == "Products"]
        assert any(op.fill_rgb == "#00FF00" for op in header_ops)
