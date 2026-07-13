from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.application import schema_maintenance
from spreadsheet_handling.domain.schema_maintenance import (
    SchemaMaintenanceRequest,
    SchemaOperationKind,
)
from spreadsheet_handling.pipeline.types import BoundStep

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def test_run_schema_maintenance_builds_private_bound_step_and_calls_orchestrate(
    monkeypatch,
) -> None:
    called = {}

    def fake_orchestrate(**kwargs):
        called.update(kwargs)
        step = kwargs["steps"][0]
        assert isinstance(step, BoundStep)
        assert step.name == schema_maintenance.PRIVATE_STEP_NAME
        step({"items": pd.DataFrame({"name": ["Item"]})})
        return {"items": pd.DataFrame({"name": ["Item"], "slug": ["Item"]})}

    monkeypatch.setattr(schema_maintenance, "orchestrate", fake_orchestrate)

    report = schema_maintenance.run_schema_maintenance(
        input={"kind": "json_dir", "path": "in"},
        output={"kind": "discard", "path": "__discard__"},
        request=_request(target_column="slug"),
    )

    assert called["input"] == {"kind": "json_dir", "path": "in"}
    assert called["output"] == {"kind": "discard", "path": "__discard__"}
    assert report.operation.kind is SchemaOperationKind.ADD_COLUMN
    assert report.frame_changes[0].target_column == "slug"


def test_blocked_schema_maintenance_does_not_persist(monkeypatch) -> None:
    from spreadsheet_handling.application import orchestrator

    monkeypatch.setattr(
        orchestrator,
        "_load_frames",
        lambda *_args, **_kwargs: {
            "items": pd.DataFrame({"name": ["Item"]}),
        },
    )

    def fail_save(*_args, **_kwargs) -> None:
        raise AssertionError("blocked schema maintenance must not persist")

    monkeypatch.setattr(orchestrator, "_save_frames", fail_save)

    report = schema_maintenance.run_schema_maintenance(
        input={"kind": "json_dir", "path": "in"},
        output={"kind": "json_dir", "path": "out"},
        request=_request(target_column="name"),
    )

    assert report.blocked is True


def test_run_schema_maintenance_returns_blocked_report_when_step_aborts(
    monkeypatch,
) -> None:
    def fake_orchestrate(**kwargs):
        kwargs["steps"][0]({"items": pd.DataFrame({"name": ["Item"]})})
        raise AssertionError("blocked schema maintenance should abort the orchestrator")

    monkeypatch.setattr(schema_maintenance, "orchestrate", fake_orchestrate)

    report = schema_maintenance.run_schema_maintenance(
        input={"kind": "json_dir", "path": "in"},
        output={"kind": "json_dir", "path": "out"},
        request=_request(target_column="name"),
    )

    assert report.blocked is True
    assert report.failures[0].code == "target_column_exists"


def _request(*, target_column: str) -> SchemaMaintenanceRequest:
    return SchemaMaintenanceRequest(
        kind=SchemaOperationKind.ADD_COLUMN,
        target_frame="items",
        target_column=target_column,
    )
