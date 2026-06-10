from __future__ import annotations

from . import columns
from .model import Frames, SchemaMaintenanceRequest, SchemaMaintenanceResult, SchemaOperationKind


def apply_schema_maintenance(
    frames: Frames,
    request: SchemaMaintenanceRequest,
) -> SchemaMaintenanceResult:
    if request.kind == SchemaOperationKind.ADD_COLUMN:
        return columns.add_column(frames, request)
    if request.kind == SchemaOperationKind.DROP_COLUMN:
        return columns.drop_column(frames, request)
    if request.kind == SchemaOperationKind.RENAME_COLUMN:
        return columns.rename_column(frames, request)
    if request.kind == SchemaOperationKind.REORDER_COLUMNS:
        return columns.reorder_columns(frames, request)
    raise ValueError(f"Unsupported schema maintenance operation: {request.kind!r}")


def add_column(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = columns.validate_request_kind(request, SchemaOperationKind.ADD_COLUMN)
    if failure is not None:
        return SchemaMaintenanceResult(
            frames=dict(frames),
            report=columns.SchemaMaintenanceReport(operation=request, failures=(failure,)),
        )
    return columns.add_column(frames, request)


def drop_column(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = columns.validate_request_kind(request, SchemaOperationKind.DROP_COLUMN)
    if failure is not None:
        return SchemaMaintenanceResult(
            frames=dict(frames),
            report=columns.SchemaMaintenanceReport(operation=request, failures=(failure,)),
        )
    return columns.drop_column(frames, request)


def rename_column(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = columns.validate_request_kind(request, SchemaOperationKind.RENAME_COLUMN)
    if failure is not None:
        return SchemaMaintenanceResult(
            frames=dict(frames),
            report=columns.SchemaMaintenanceReport(operation=request, failures=(failure,)),
        )
    return columns.rename_column(frames, request)


def reorder_columns(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = columns.validate_request_kind(request, SchemaOperationKind.REORDER_COLUMNS)
    if failure is not None:
        return SchemaMaintenanceResult(
            frames=dict(frames),
            report=columns.SchemaMaintenanceReport(operation=request, failures=(failure,)),
        )
    return columns.reorder_columns(frames, request)
