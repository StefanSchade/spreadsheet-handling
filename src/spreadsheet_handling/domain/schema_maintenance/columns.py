from __future__ import annotations

from typing import Any

import pandas as pd

from .model import (
    ColumnPlacement,
    FrameChange,
    Frames,
    ReorderSpec,
    SchemaMaintenanceFailure,
    SchemaMaintenanceReport,
    SchemaMaintenanceRequest,
    SchemaMaintenanceResult,
    SchemaOperationKind,
)

ALLOWED_PLACEMENT_MODES = frozenset({"append", "before", "after"})
ALLOWED_REORDER_MODES = frozenset({"complete", "listed_first", "listed_last"})


def add_column(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = _require_dataframe(frames, request.target_frame)
    if failure is not None:
        return _blocked(frames, request, failure)

    target_column = request.target_column
    if not target_column:
        return _blocked(
            frames,
            request,
            _failure(
                "missing_target_column",
                "add_column requires target_column",
                request.target_frame,
            ),
        )

    frame = frames[request.target_frame]
    if target_column in frame.columns:
        return _blocked(
            frames,
            request,
            _failure(
                "target_column_exists",
                f"Column {target_column!r} already exists in frame {request.target_frame!r}",
                request.target_frame,
                target_column,
            ),
        )

    placement = request.placement or ColumnPlacement()
    placement_failure = _validate_placement(frame, placement, request.target_frame)
    if placement_failure is not None:
        return _blocked(frames, request, placement_failure)

    out = _copy_frames(frames)
    updated = frame.copy()
    insert_at = _insert_index(updated, placement)
    updated.insert(insert_at, target_column, request.default_value)
    out[request.target_frame] = updated
    return _success(
        out,
        request,
        FrameChange(
            frame=request.target_frame,
            kind=SchemaOperationKind.ADD_COLUMN,
            source_column=None,
            target_column=target_column,
            detail=f"Added column {target_column!r}",
        ),
    )


def drop_column(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = _require_dataframe(frames, request.target_frame)
    if failure is not None:
        return _blocked(frames, request, failure)

    source_column = request.source_column
    if not source_column:
        return _blocked(
            frames,
            request,
            _failure(
                "missing_source_column",
                "drop_column requires source_column",
                request.target_frame,
            ),
        )

    frame = frames[request.target_frame]
    if source_column not in frame.columns:
        return _blocked(
            frames,
            request,
            _failure(
                "source_column_missing",
                f"Column {source_column!r} does not exist in frame {request.target_frame!r}",
                request.target_frame,
                source_column,
            ),
        )

    out = _copy_frames(frames)
    out[request.target_frame] = frame.drop(columns=[source_column]).copy()
    return _success(
        out,
        request,
        FrameChange(
            frame=request.target_frame,
            kind=SchemaOperationKind.DROP_COLUMN,
            source_column=source_column,
            target_column=None,
            detail=f"Dropped column {source_column!r}",
        ),
    )


def rename_column(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = _require_dataframe(frames, request.target_frame)
    if failure is not None:
        return _blocked(frames, request, failure)

    source_column = request.source_column
    target_column = request.target_column
    if not source_column:
        return _blocked(
            frames,
            request,
            _failure(
                "missing_source_column",
                "rename_column requires source_column",
                request.target_frame,
            ),
        )
    if not target_column:
        return _blocked(
            frames,
            request,
            _failure(
                "missing_target_column",
                "rename_column requires target_column",
                request.target_frame,
            ),
        )

    frame = frames[request.target_frame]
    if source_column not in frame.columns:
        return _blocked(
            frames,
            request,
            _failure(
                "source_column_missing",
                f"Column {source_column!r} does not exist in frame {request.target_frame!r}",
                request.target_frame,
                source_column,
            ),
        )
    if target_column in frame.columns:
        return _blocked(
            frames,
            request,
            _failure(
                "target_column_exists",
                f"Column {target_column!r} already exists in frame {request.target_frame!r}",
                request.target_frame,
                target_column,
            ),
        )

    out = _copy_frames(frames)
    out[request.target_frame] = frame.rename(columns={source_column: target_column}).copy()
    return _success(
        out,
        request,
        FrameChange(
            frame=request.target_frame,
            kind=SchemaOperationKind.RENAME_COLUMN,
            source_column=source_column,
            target_column=target_column,
            detail=f"Renamed column {source_column!r} to {target_column!r}",
        ),
    )


def reorder_columns(frames: Frames, request: SchemaMaintenanceRequest) -> SchemaMaintenanceResult:
    failure = _require_dataframe(frames, request.target_frame)
    if failure is not None:
        return _blocked(frames, request, failure)

    reorder = request.reorder
    if reorder is None:
        return _blocked(
            frames,
            request,
            _failure(
                "missing_reorder_spec",
                "reorder_columns requires reorder",
                request.target_frame,
            ),
        )

    frame = frames[request.target_frame]
    validation_failure = _validate_reorder_spec(frame, reorder, request.target_frame)
    if validation_failure is not None:
        return _blocked(frames, request, validation_failure)

    ordered_columns = _ordered_columns(frame, reorder)
    out = _copy_frames(frames)
    out[request.target_frame] = frame.loc[:, ordered_columns].copy()
    return _success(
        out,
        request,
        FrameChange(
            frame=request.target_frame,
            kind=SchemaOperationKind.REORDER_COLUMNS,
            source_column=None,
            target_column=None,
            detail=f"Reordered columns using {reorder.mode!r}",
        ),
    )


def _require_dataframe(frames: Frames, frame_name: str) -> SchemaMaintenanceFailure | None:
    value = frames.get(frame_name)
    if isinstance(value, pd.DataFrame):
        return None
    return _failure(
        "missing_target_frame",
        f"Target frame {frame_name!r} does not exist",
        frame_name,
    )


def _validate_placement(
    frame: pd.DataFrame,
    placement: ColumnPlacement,
    frame_name: str,
) -> SchemaMaintenanceFailure | None:
    if placement.mode not in ALLOWED_PLACEMENT_MODES:
        return _failure(
            "invalid_placement_mode",
            f"Unknown placement mode {placement.mode!r}; expected one of "
            f"{sorted(ALLOWED_PLACEMENT_MODES)!r}",
            frame_name,
        )
    if placement.mode == "append":
        return None
    if placement.column is None:
        return _failure(
            "missing_placement_column",
            f"Placement mode {placement.mode!r} requires a column",
            frame_name,
        )
    if placement.column not in frame.columns:
        return _failure(
            "placement_column_missing",
            f"Placement column {placement.column!r} does not exist in frame {frame_name!r}",
            frame_name,
            placement.column,
        )
    return None


def _insert_index(frame: pd.DataFrame, placement: ColumnPlacement) -> int:
    if placement.mode == "append":
        return len(frame.columns)
    assert placement.column is not None
    index = list(frame.columns).index(placement.column)
    if placement.mode == "after":
        return index + 1
    return index


def _validate_reorder_spec(
    frame: pd.DataFrame,
    reorder: ReorderSpec,
    frame_name: str,
) -> SchemaMaintenanceFailure | None:
    if reorder.mode not in ALLOWED_REORDER_MODES:
        return _failure(
            "invalid_reorder_mode",
            f"Unknown reorder mode {reorder.mode!r}; expected one of "
            f"{sorted(ALLOWED_REORDER_MODES)!r}",
            frame_name,
        )

    requested = list(reorder.columns)
    duplicates = sorted({column for column in requested if requested.count(column) > 1})
    if duplicates:
        return _failure(
            "duplicate_requested_columns",
            f"Requested columns contain duplicates: {duplicates!r}",
            frame_name,
            duplicates[0],
        )

    existing = set(frame.columns)
    unknown = [column for column in requested if column not in existing]
    if unknown:
        return _failure(
            "unknown_requested_columns",
            f"Requested columns are not present in frame {frame_name!r}: {unknown!r}",
            frame_name,
            unknown[0],
        )

    if reorder.mode == "complete":
        missing = [column for column in frame.columns if column not in requested]
        if missing:
            return _failure(
                "incomplete_column_order",
                f"Complete reorder is missing columns: {missing!r}",
                frame_name,
                missing[0],
            )
    return None


def _ordered_columns(frame: pd.DataFrame, reorder: ReorderSpec) -> list[Any]:
    requested = list(reorder.columns)
    if reorder.mode == "complete":
        return requested

    omitted = [column for column in frame.columns if column not in requested]
    if reorder.mode == "listed_first":
        return requested + omitted
    return omitted + requested


def _copy_frames(frames: Frames) -> Frames:
    return dict(frames)


def _blocked(
    frames: Frames,
    request: SchemaMaintenanceRequest,
    failure: SchemaMaintenanceFailure,
) -> SchemaMaintenanceResult:
    report = SchemaMaintenanceReport(operation=request, failures=(failure,))
    return SchemaMaintenanceResult(frames=_copy_frames(frames), report=report)


def _success(
    frames: Frames,
    request: SchemaMaintenanceRequest,
    change: FrameChange,
) -> SchemaMaintenanceResult:
    report = SchemaMaintenanceReport(operation=request, frame_changes=(change,))
    return SchemaMaintenanceResult(frames=frames, report=report)


def _failure(
    code: str,
    message: str,
    frame: str | None,
    column: str | None = None,
) -> SchemaMaintenanceFailure:
    return SchemaMaintenanceFailure(
        code=code,
        message=message,
        frame=frame,
        column=column,
    )


def validate_request_kind(
    request: SchemaMaintenanceRequest,
    kind: SchemaOperationKind,
) -> SchemaMaintenanceFailure | None:
    if request.kind == kind:
        return None
    return _failure(
        "operation_kind_mismatch",
        f"Request kind {request.kind.value!r} does not match operation {kind.value!r}",
        request.target_frame,
    )
