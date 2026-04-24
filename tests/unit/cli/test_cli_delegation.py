"""Tests that CLI entry points delegate to orchestrate().

Each CLI (sheets-run, sheets-pack, sheets-unpack) should build config
from its arguments and then call orchestrate() - no direct I/O logic.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


pytestmark = pytest.mark.ftr("FTR-ONE-ORCHESTRATOR")


def _write_json_dir(path: Path, data: dict[str, list[dict]]) -> None:
    """Write a minimal JSON directory (one .json file per sheet)."""
    path.mkdir(parents=True, exist_ok=True)
    for name, records in data.items():
        (path / f"{name}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )


SAMPLE_DATA = {
    "products": [
        {"id": "a", "name": "Alpha"},
        {"id": "b", "name": "Bravo"},
    ]
}


class TestSheetsPack:

    def test_delegates_to_orchestrate(self, tmp_path: Path) -> None:
        in_dir = tmp_path / "in"
        out_file = tmp_path / "out.xlsx"
        _write_json_dir(in_dir, SAMPLE_DATA)

        with patch("spreadsheet_handling.cli.apps.sheets_pack.orchestrate") as mock_orch:
            from spreadsheet_handling.cli.apps.sheets_pack import main

            rc = main([str(in_dir), "-o", str(out_file)])

        assert rc == 0
        mock_orch.assert_called_once()
        call_kw = mock_orch.call_args.kwargs
        assert call_kw["input"] == {"kind": "json", "path": str(in_dir)}
        assert call_kw["output"] == {"kind": "xlsx", "path": str(out_file)}

    def test_respects_input_kind(self, tmp_path: Path) -> None:
        in_dir = tmp_path / "in"
        out_file = tmp_path / "out.xlsx"
        in_dir.mkdir()

        with patch("spreadsheet_handling.cli.apps.sheets_pack.orchestrate") as mock_orch:
            from spreadsheet_handling.cli.apps.sheets_pack import main

            main([str(in_dir), "-o", str(out_file), "--input-kind", "csv_dir"])

        call_kw = mock_orch.call_args.kwargs
        assert call_kw["input"]["kind"] == "csv_dir"


class TestSheetsUnpack:

    def test_delegates_to_orchestrate(self, tmp_path: Path) -> None:
        wb = tmp_path / "input.xlsx"
        out_dir = tmp_path / "out"
        wb.touch()

        with patch("spreadsheet_handling.cli.apps.sheets_unpack.orchestrate") as mock_orch:
            from spreadsheet_handling.cli.apps.sheets_unpack import main

            rc = main([str(wb), "-o", str(out_dir)])

        assert rc == 0
        mock_orch.assert_called_once()
        call_kw = mock_orch.call_args.kwargs
        assert call_kw["input"] == {"kind": "xlsx", "path": str(wb)}
        assert call_kw["output"] == {"kind": "json_dir", "path": str(out_dir)}


class TestSheetsRun:

    def test_delegates_with_cli_overrides(self, tmp_path: Path) -> None:
        in_dir = tmp_path / "in"
        out_dir = tmp_path / "out"
        in_dir.mkdir()

        with patch("spreadsheet_handling.cli.apps.run.orchestrate") as mock_orch:
            from spreadsheet_handling.cli.apps.run import main

            rc = main(
                [
                    "--in-kind",
                    "json_dir",
                    "--in-path",
                    str(in_dir),
                    "--out-kind",
                    "json_dir",
                    "--out-path",
                    str(out_dir),
                ]
            )

        assert rc == 0
        mock_orch.assert_called_once()
        call_kw = mock_orch.call_args.kwargs
        assert call_kw["input"]["kind"] == "json_dir"
        assert call_kw["input"]["path"] == str(in_dir)
        assert call_kw["output"]["kind"] == "json_dir"
        assert call_kw["output"]["path"] == str(out_dir)

    def test_delegates_with_config_yaml(self, tmp_path: Path) -> None:
        in_dir = tmp_path / "in"
        out_dir = tmp_path / "out"
        _write_json_dir(in_dir, SAMPLE_DATA)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            f"""\
io:
  input:
    kind: json_dir
    path: "{in_dir.as_posix()}"
  output:
    kind: json_dir
    path: "{out_dir.as_posix()}"
""",
            encoding="utf-8",
        )

        with patch("spreadsheet_handling.cli.apps.run.orchestrate") as mock_orch:
            from spreadsheet_handling.cli.apps.run import main

            rc = main(["--config", str(config_file)])

        assert rc == 0
        mock_orch.assert_called_once()
        call_kw = mock_orch.call_args.kwargs
        assert call_kw["input"]["kind"] == "json_dir"
        assert call_kw["output"]["kind"] == "json_dir"
