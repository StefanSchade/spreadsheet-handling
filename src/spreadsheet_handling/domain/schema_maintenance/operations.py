from __future__ import annotations

from . import columns
from .meta_update import apply_metadata_rules
from .model import (
    Frames,
    SchemaMaintenanceReport,
    SchemaMaintenanceRequest,
    SchemaMaintenanceResult,
    SchemaOperationKind,
)


def apply_schema_maintenance(
    frames: Frames,
    request: SchemaMaintenanceRequest,
) -> SchemaMaintenanceResult:
    if request.kind == SchemaOperationKind.ADD_COLUMN:
        return _with_metadata(frames, columns.add_column(frames, request), request)
    if request.kind == SchemaOperationKind.DROP_COLUMN:
        return _with_metadata(frames, columns.drop_column(frames, request), request)
    if request.kind == SchemaOperationKind.RENAME_COLUMN:
        return _with_metadata(frames, columns.rename_column(frames, request), request)
    if request.kind == SchemaOperationKind.REORDER_COLUMNS:
        return _with_metadata(frames, columns.reorder_columns(frames, request), request)
    raise ValueError(f"Unsupported schema maintenance operation: {request.kind!r}")


def add_column(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = columns.validate_request_kind(request, SchemaOperationKind.ADD_COLUMN)
    if failure is not None:
        return SchemaMaintenanceResult(
            frames=dict(frames),
            report=SchemaMaintenanceReport(operation=request, failures=(failure,)),
        )
    return apply_schema_maintenance(frames, request)


def drop_column(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = columns.validate_request_kind(request, SchemaOperationKind.DROP_COLUMN)
    if failure is not None:
        return SchemaMaintenanceResult(
            frames=dict(frames),
            report=SchemaMaintenanceReport(operation=request, failures=(failure,)),
        )
    return apply_schema_maintenance(frames, request)


def rename_column(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = columns.validate_request_kind(request, SchemaOperationKind.RENAME_COLUMN)
    if failure is not None:
        return SchemaMaintenanceResult(
            frames=dict(frames),
            report=SchemaMaintenanceReport(operation=request, failures=(failure,)),
        )
    return apply_schema_maintenance(frames, request)


def reorder_columns(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = columns.validate_request_kind(request, SchemaOperationKind.REORDER_COLUMNS)
    if failure is not None:
        return SchemaMaintenanceResult(
            frames=dict(frames),
            report=SchemaMaintenanceReport(operation=request, failures=(failure,)),
        )
    return apply_schema_maintenance(frames, request)


def _with_metadata(
    original_frames: Frames,
    frame_result: SchemaMaintenanceResult,
    request: SchemaMaintenanceRequest,
) -> SchemaMaintenanceResult:
    if frame_result.report.blocked:
        return frame_result
    return apply_metadata_rules(
        original_frames=original_frames,
        proposed_frames=frame_result.frames,
        request=request,
        frame_changes=frame_result.report.frame_changes,
    )
