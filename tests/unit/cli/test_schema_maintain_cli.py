from __future__ import annotations

import json
from pathlib import Path

import pytest

from spreadsheet_handling.cli.apps import schema_maintain
from spreadsheet_handling.domain.schema_maintenance import (
    FrameChange,
    SchemaMaintenanceFailure,
    SchemaMaintenanceReport,
    SchemaMaintenanceRequest,
    SchemaOperationKind,
    WriteIntent,
)

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def test_cli_delegates_to_schema_maintenance_application(monkeypatch, capsys) -> None:
    called = {}

    def fake_run_schema_maintenance(**kwargs):
        called.update(kwargs)
        return _report()

    monkeypatch.setattr(schema_maintain, "run_schema_maintenance", fake_run_schema_maintenance)

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
    assert called["input"] == {"kind": "json_dir", "path": "in"}
    assert called["output"] == {"kind": "discard", "path": "__discard__"}
    assert called["request"].kind is SchemaOperationKind.ADD_COLUMN
    report = json.loads(capsys.readouterr().out)
    assert report["operation"]["kind"] == "add_column"
    assert report["frame_changes"][0]["target_column"] == "slug"


def test_write_mode_requires_output_path(monkeypatch) -> None:
    def fail_run_schema_maintenance(**kwargs):
        raise AssertionError("run_schema_maintenance should not run without write output")

    monkeypatch.setattr(schema_maintain, "run_schema_maintenance", fail_run_schema_maintenance)

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

    def fake_run_schema_maintenance(**kwargs):
        called.update(kwargs)
        return _report(write_intent=WriteIntent.WRITE)

    monkeypatch.setattr(schema_maintain, "run_schema_maintenance", fake_run_schema_maintenance)
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
    def fake_run_schema_maintenance(**kwargs):
        return _report()

    monkeypatch.setattr(schema_maintain, "run_schema_maintenance", fake_run_schema_maintenance)
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
    def fake_run_schema_maintenance(**kwargs):
        return _report(
            target_column="name",
            failures=(
                SchemaMaintenanceFailure(
                    code="target_column_exists",
                    message="Target column already exists",
                    frame="items",
                    column="name",
                ),
            ),
            write_intent=WriteIntent.WRITE,
        )

    monkeypatch.setattr(schema_maintain, "run_schema_maintenance", fake_run_schema_maintenance)

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


def _report(
    *,
    target_column: str = "slug",
    failures: tuple[SchemaMaintenanceFailure, ...] = (),
    write_intent: WriteIntent = WriteIntent.DRY_RUN,
) -> SchemaMaintenanceReport:
    request = SchemaMaintenanceRequest(
        kind=SchemaOperationKind.ADD_COLUMN,
        target_frame="items",
        target_column=target_column,
        write_intent=write_intent,
    )
    frame_changes = ()
    if not failures:
        frame_changes = (
            FrameChange(
                frame="items",
                kind=SchemaOperationKind.ADD_COLUMN,
                source_column=None,
                target_column=target_column,
                detail=f"Added column '{target_column}'",
            ),
        )
    return SchemaMaintenanceReport(
        operation=request,
        frame_changes=frame_changes,
        failures=failures,
    )
