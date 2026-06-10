from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.cli.apps.schema_maintain import main
from spreadsheet_handling.io_backends.json_backend import read_json_dir, write_json_dir

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def _write_characters_input(path: Path) -> None:
    write_json_dir(
        {
            "characters": pd.DataFrame(
                {
                    "id": ["c1", "c2"],
                    "name": ["Ada", "Lin"],
                    "age": ["31", "29"],
                }
            ),
            "_meta": {
                "version": "1.0",
                "constraints": [{"sheet": "characters", "column": "name", "required": True}],
                "derived": {"sheets": {"characters": {"helper_columns": ["runtime_only"]}}},
            },
        },
        path,
    )


def test_json_dir_write_mode_updates_data_and_meta(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    report_path = tmp_path / "report.json"
    _write_characters_input(input_dir)

    rc = main(
        [
            "--in-kind",
            "json_dir",
            "--in-path",
            str(input_dir),
            "--write",
            "--out-kind",
            "json_dir",
            "--out-path",
            str(output_dir),
            "--op",
            "rename_column",
            "--frame",
            "characters",
            "--source-column",
            "name",
            "--target-column",
            "display_name",
            "--report",
            str(report_path),
        ]
    )

    assert rc == 0
    frames = read_json_dir(str(output_dir))
    assert frames["characters"].columns.tolist() == ["id", "display_name", "age"]
    assert frames["characters"]["display_name"].tolist() == ["Ada", "Lin"]
    assert frames["_meta"]["constraints"] == [
        {"sheet": "characters", "column": "display_name", "required": True}
    ]
    assert "derived" not in frames["_meta"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["metadata_changes"][0]["action"] == "ignored_derived"
    assert any(change["action"] == "updated" for change in report["metadata_changes"])


def test_json_dir_dry_run_writes_no_output_artifact(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    input_dir = tmp_path / "input"
    _write_characters_input(input_dir)
    monkeypatch.chdir(tmp_path)

    rc = main(
        [
            "--in-kind",
            "json_dir",
            "--in-path",
            str(input_dir),
            "--op",
            "add_column",
            "--frame",
            "characters",
            "--target-column",
            "slug",
        ]
    )

    assert rc == 0
    assert not (tmp_path / "__discard__").exists()
    assert not (tmp_path / "output").exists()
    report = json.loads(capsys.readouterr().out)
    assert report["operation"]["write_intent"] == "dry_run"
    assert report["frame_changes"][0]["target_column"] == "slug"


def test_blocked_json_dir_write_emits_report_and_writes_no_output(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    report_path = tmp_path / "blocked.json"
    _write_characters_input(input_dir)

    rc = main(
        [
            "--in-kind",
            "json_dir",
            "--in-path",
            str(input_dir),
            "--write",
            "--out-kind",
            "json_dir",
            "--out-path",
            str(output_dir),
            "--op",
            "drop_column",
            "--frame",
            "characters",
            "--source-column",
            "name",
            "--report",
            str(report_path),
        ]
    )

    assert rc == 1
    assert not output_dir.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["failures"][0]["code"] == "blocking_metadata_reference"
