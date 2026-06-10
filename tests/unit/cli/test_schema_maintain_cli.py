from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.cli.apps import schema_maintain
from spreadsheet_handling.pipeline.types import BoundStep

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def test_cli_builds_private_bound_step_and_calls_orchestrate(monkeypatch, capsys) -> None:
    called = {}

    def fake_orchestrate(**kwargs):
        called.update(kwargs)
        step = kwargs["steps"][0]
        assert isinstance(step, BoundStep)
        assert step.name == schema_maintain.PRIVATE_STEP_NAME
        return step({"items": pd.DataFrame({"name": ["Item"]})})

    monkeypatch.setattr(schema_maintain, "orchestrate", fake_orchestrate)

    rc = schema_maintain.main(
        [
            "--in-kind",
            "json_dir",
            "--in-path",
            "in",
            "--op",
            "add_column",
            "--frame",
            "items",
            "--target-column",
            "slug",
        ]
    )

    assert rc == 0
    assert called["output"] == {"kind": "discard", "path": "__discard__"}
    report = json.loads(capsys.readouterr().out)
    assert report["operation"]["kind"] == "add_column"
    assert report["frame_changes"][0]["target_column"] == "slug"


def test_write_mode_requires_output_path(monkeypatch) -> None:
    def fail_orchestrate(**kwargs):
        raise AssertionError("orchestrate should not run without write output")

    monkeypatch.setattr(schema_maintain, "orchestrate", fail_orchestrate)

    with pytest.raises(SystemExit, match="Write mode requires --out-path"):
        schema_maintain.main(
            [
                "--in-kind",
                "json_dir",
                "--in-path",
                "in",
                "--write",
                "--out-kind",
                "json_dir",
                "--op",
                "add_column",
                "--frame",
                "items",
                "--target-column",
                "slug",
            ]
        )


def test_write_mode_uses_user_output_and_not_discard(monkeypatch, tmp_path: Path) -> None:
    called = {}

    def fake_orchestrate(**kwargs):
        called.update(kwargs)
        return kwargs["steps"][0]({"items": pd.DataFrame({"name": ["Item"]})})

    monkeypatch.setattr(schema_maintain, "orchestrate", fake_orchestrate)
    out_path = tmp_path / "out"

    rc = schema_maintain.main(
        [
            "--in-kind",
            "json_dir",
            "--in-path",
            "in",
            "--write",
            "--out-kind",
            "json_dir",
            "--out-path",
            str(out_path),
            "--op",
            "add_column",
            "--frame",
            "items",
            "--target-column",
            "slug",
        ]
    )

    assert rc == 0
    assert called["output"] == {"kind": "json_dir", "path": str(out_path)}


def test_report_is_written_to_path_when_requested(monkeypatch, tmp_path: Path, capsys) -> None:
    def fake_orchestrate(**kwargs):
        return kwargs["steps"][0]({"items": pd.DataFrame({"name": ["Item"]})})

    monkeypatch.setattr(schema_maintain, "orchestrate", fake_orchestrate)
    report_path = tmp_path / "reports" / "schema.json"

    rc = schema_maintain.main(
        [
            "--in-kind",
            "json_dir",
            "--in-path",
            "in",
            "--op",
            "add_column",
            "--frame",
            "items",
            "--target-column",
            "slug",
            "--report",
            str(report_path),
        ]
    )

    assert rc == 0
    assert capsys.readouterr().out == ""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["operation"]["target_frame"] == "items"


def test_blocked_operation_still_emits_report(monkeypatch, capsys) -> None:
    def fake_orchestrate(**kwargs):
        return kwargs["steps"][0]({"items": pd.DataFrame({"name": ["Item"]})})

    monkeypatch.setattr(schema_maintain, "orchestrate", fake_orchestrate)

    rc = schema_maintain.main(
        [
            "--in-kind",
            "json_dir",
            "--in-path",
            "in",
            "--write",
            "--out-kind",
            "json_dir",
            "--out-path",
            "out",
            "--op",
            "add_column",
            "--frame",
            "items",
            "--target-column",
            "name",
        ]
    )

    assert rc == 1
    report = json.loads(capsys.readouterr().out)
    assert report["failures"][0]["code"] == "target_column_exists"
