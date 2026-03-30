# tests/unit/cli/test_cli_default_pipelines.py
"""
FTR-CLI-DEFAULT-PIPELINES — Pack/Unpack with predefined default pipelines.

Acceptance:
- sheets-pack produces XLSX with header styling and AutoFilter without explicit YAML.
- sheets-unpack remains backward compatible (no steps needed).
- sheets-pack --config custom.yaml overrides the default pipeline.
- sheets-pack --no-defaults suppresses the default pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.ftr("FTR-CLI-DEFAULT-PIPELINES")


def _write_json_dir(path: Path, data: dict) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, records in data.items():
        (path / f"{name}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )


SAMPLE = {
    "products": [
        {"id": "P-1", "name": "Alpha"},
        {"id": "P-2", "name": "Beta"},
    ]
}


class TestPackDefaultPipeline:

    def test_pack_passes_default_steps(self, tmp_path: Path):
        """Without --config or --no-defaults, pack passes default steps."""
        in_dir = tmp_path / "in"
        out = tmp_path / "out.xlsx"
        _write_json_dir(in_dir, SAMPLE)

        with patch("spreadsheet_handling.cli.apps.sheets_pack.orchestrate") as mock:
            from spreadsheet_handling.cli.apps.sheets_pack import main
            main([str(in_dir), "-o", str(out)])

        kw = mock.call_args.kwargs
        assert kw["steps"] is not None
        assert len(kw["steps"]) >= 1
        assert kw["steps"][0].name == "bootstrap_meta"

    def test_pack_no_defaults_suppresses_steps(self, tmp_path: Path):
        in_dir = tmp_path / "in"
        out = tmp_path / "out.xlsx"
        in_dir.mkdir()

        with patch("spreadsheet_handling.cli.apps.sheets_pack.orchestrate") as mock:
            from spreadsheet_handling.cli.apps.sheets_pack import main
            main([str(in_dir), "-o", str(out), "--no-defaults"])

        kw = mock.call_args.kwargs
        assert kw["steps"] is None

    def test_pack_config_overrides_defaults(self, tmp_path: Path):
        in_dir = tmp_path / "in"
        out = tmp_path / "out.xlsx"
        in_dir.mkdir()

        cfg = tmp_path / "pipe.yaml"
        cfg.write_text("pipeline:\n  - step: identity\n", encoding="utf-8")

        with patch("spreadsheet_handling.cli.apps.sheets_pack.orchestrate") as mock:
            from spreadsheet_handling.cli.apps.sheets_pack import main
            main([str(in_dir), "-o", str(out), "--config", str(cfg)])

        kw = mock.call_args.kwargs
        assert kw["steps"] is not None
        assert kw["steps"][0].name == "identity"


class TestUnpackBackwardCompat:

    def test_unpack_still_passes_no_steps(self, tmp_path: Path):
        """Unpack remains backward compatible — no steps."""
        wb = tmp_path / "in.xlsx"
        out = tmp_path / "out"
        wb.touch()

        with patch("spreadsheet_handling.cli.apps.sheets_unpack.orchestrate") as mock:
            from spreadsheet_handling.cli.apps.sheets_unpack import main
            main([str(wb), "-o", str(out)])

        kw = mock.call_args.kwargs
        assert "steps" not in kw or kw.get("steps") is None


class TestPackEndToEnd:

    def test_pack_produces_styled_xlsx(self, tmp_path: Path):
        """End-to-end: pack produces XLSX with AutoFilter without explicit YAML."""
        from openpyxl import load_workbook
        from spreadsheet_handling.cli.apps.sheets_pack import main

        in_dir = tmp_path / "in"
        out = tmp_path / "out.xlsx"
        _write_json_dir(in_dir, SAMPLE)

        main([str(in_dir), "-o", str(out)])

        wb = load_workbook(out)
        ws = wb["products"]
        # AutoFilter should be set (from bootstrap_meta default)
        assert ws.auto_filter and ws.auto_filter.ref
        wb.close()
