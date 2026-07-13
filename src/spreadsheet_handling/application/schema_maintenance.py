"""Application use case for command-only schema maintenance.

Schema maintenance is intentionally not exposed as a public,
YAML-configurable pipeline step. A private BoundStep is constructed only to
reuse the orchestrator's I/O and persistence-boundary flow.
"""

from __future__ import annotations

from .orchestrator import IODescriptorLike, orchestrate
from ..domain.schema_maintenance import (
    SchemaMaintenanceReport,
    SchemaMaintenanceRequest,
    SchemaMaintenanceResult,
    apply_schema_maintenance,
)
from ..pipeline.types import BoundStep, Frames

PRIVATE_STEP_NAME = "_schema_maintenance_private"


class _SchemaMaintenanceBlocked(RuntimeError):
    def __init__(self, report: SchemaMaintenanceReport) -> None:
        super().__init__("Schema maintenance operation blocked")
        self.report = report


def run_schema_maintenance(
    *,
    input: IODescriptorLike,
    output: IODescriptorLike,
    request: SchemaMaintenanceRequest,
) -> SchemaMaintenanceReport:
    """Run one schema-maintenance command through the shared orchestrator."""

    # BoundStep has a Frames -> Frames contract. Capture the report out of band so
    # the application use case can return it after orchestration completes.
    collector: list[SchemaMaintenanceReport] = []
    step = _build_private_step(request, collector)

    try:
        orchestrate(input=input, output=output, steps=[step])
    except _SchemaMaintenanceBlocked as exc:
        return exc.report

    return _require_report(collector)


def _build_private_step(
    request: SchemaMaintenanceRequest,
    collector: list[SchemaMaintenanceReport],
) -> BoundStep:
    def run(frames: Frames) -> Frames:
        result: SchemaMaintenanceResult = apply_schema_maintenance(frames, request)
        collector.append(result.report)
        if result.report.blocked:
            raise _SchemaMaintenanceBlocked(result.report)
        return result.frames

    return BoundStep(
        name=PRIVATE_STEP_NAME,
        config={"operation": request.kind.value, "target_frame": request.target_frame},
        fn=run,
    )


def _require_report(collector: list[SchemaMaintenanceReport]) -> SchemaMaintenanceReport:
    if not collector:
        raise RuntimeError("Schema maintenance did not produce a report")
    return collector[-1]


__all__ = ["PRIVATE_STEP_NAME", "run_schema_maintenance"]
