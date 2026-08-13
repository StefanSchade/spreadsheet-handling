"""Ordinary Frames structural admission for Trusted Ingress slice E2.

This internal, validate-only seam recognizes the initial ordinary carrier set,
reuses the established physical-column authority, and visits every ordinary
data cell through E1.  Reserved ``_meta`` content remains opaque here for E3;
controlled framework roles and macro-flow wiring remain E4 and E5 concerns.
"""

from __future__ import annotations

from typing import Any, Literal, TypeVar

import pandas as pd

from spreadsheet_handling.core.exact_table import ExactTable
from spreadsheet_handling.domain.tabular import ensure_unique_physical_column_labels

from .scalar_admission import OrdinaryScalarAdmissionError, admit_ordinary_scalar

_FramesT = TypeVar("_FramesT", bound=dict[str, Any])
_CarrierRole = Literal["frames", "dataframe", "exact_table"]
_FailureKind = Literal[
    "invalid_frames_mapping",
    "invalid_frame_name",
    "unsupported_top_level_carrier",
    "invalid_physical_columns",
    "invalid_exact_table_header_rows",
    "invalid_exact_table_n_cols",
    "invalid_exact_table_header_grid_height",
    "invalid_exact_table_header_row_width",
    "invalid_exact_table_data_row_width",
    "invalid_exact_table_header_cell",
    "unsupported_scalar_carrier",
]
_PayloadEntry = tuple[int, str, pd.DataFrame | ExactTable, _CarrierRole]


class OrdinaryStructureAdmissionError(TypeError):
    """A safe, positional E2 rejection with no rejected value or label."""

    def __init__(
        self,
        *,
        kind: _FailureKind,
        carrier_role: _CarrierRole,
        frame_ordinal: int | None = None,
        frame_name: str | None = None,
        row_ordinal: int | None = None,
        column_ordinal: int | None = None,
    ) -> None:
        self.kind = kind
        self.carrier_role = carrier_role
        self.frame_ordinal = frame_ordinal
        self.frame_name = frame_name
        self.row_ordinal = row_ordinal
        self.column_ordinal = column_ordinal
        super().__init__(
            _safe_admission_message(
                kind=kind,
                carrier_role=carrier_role,
                frame_ordinal=frame_ordinal,
                frame_name=frame_name,
                row_ordinal=row_ordinal,
                column_ordinal=column_ordinal,
            )
        )


def _safe_admission_message(
    *,
    kind: _FailureKind,
    carrier_role: _CarrierRole,
    frame_ordinal: int | None,
    frame_name: str | None,
    row_ordinal: int | None,
    column_ordinal: int | None,
) -> str:
    location = [f"carrier role {carrier_role}"]
    if frame_ordinal is not None:
        location.append(f"frame ordinal {frame_ordinal}")
    if frame_name is not None:
        location.append(f"frame name {frame_name!r}")
    if row_ordinal is not None:
        location.append(f"row ordinal {row_ordinal}")
    if column_ordinal is not None:
        location.append(f"column ordinal {column_ordinal}")
    return f"ordinary structural admission failed ({kind}) at {', '.join(location)}"


def _dispatch_payload_entries(frames: object) -> tuple[_PayloadEntry, ...]:
    if type(frames) is not dict:
        raise OrdinaryStructureAdmissionError(
            kind="invalid_frames_mapping",
            carrier_role="frames",
        )

    items = tuple(frames.items())
    for frame_ordinal, (frame_name, _) in enumerate(items):
        if type(frame_name) is not str:
            raise OrdinaryStructureAdmissionError(
                kind="invalid_frame_name",
                carrier_role="frames",
                frame_ordinal=frame_ordinal,
            )

    payload_entries: list[_PayloadEntry] = []
    for frame_ordinal, (frame_name, carrier) in enumerate(items):
        if frame_name == "_meta":
            continue
        if isinstance(carrier, pd.DataFrame):
            payload_entries.append((frame_ordinal, frame_name, carrier, "dataframe"))
            continue
        if type(carrier) is ExactTable:
            payload_entries.append((frame_ordinal, frame_name, carrier, "exact_table"))
            continue
        raise OrdinaryStructureAdmissionError(
            kind="unsupported_top_level_carrier",
            carrier_role="frames",
            frame_ordinal=frame_ordinal,
            frame_name=frame_name,
        )
    return tuple(payload_entries)


def _validate_dataframe_structure(
    frame: pd.DataFrame,
    *,
    frame_ordinal: int,
    frame_name: str,
) -> None:
    try:
        ensure_unique_physical_column_labels(
            frame,
            frame_name=frame_name,
            include_label_values=False,
        )
    except ValueError:
        raise OrdinaryStructureAdmissionError(
            kind="invalid_physical_columns",
            carrier_role="dataframe",
            frame_ordinal=frame_ordinal,
            frame_name=frame_name,
        ) from None


def _raise_exact_structure_error(
    kind: _FailureKind,
    *,
    frame_ordinal: int,
    frame_name: str,
    row_ordinal: int | None = None,
    column_ordinal: int | None = None,
) -> None:
    raise OrdinaryStructureAdmissionError(
        kind=kind,
        carrier_role="exact_table",
        frame_ordinal=frame_ordinal,
        frame_name=frame_name,
        row_ordinal=row_ordinal,
        column_ordinal=column_ordinal,
    )


def _validate_exact_table_structure(
    table: ExactTable,
    *,
    frame_ordinal: int,
    frame_name: str,
) -> None:
    if type(table.header_rows) is not int or table.header_rows < 0:
        _raise_exact_structure_error(
            "invalid_exact_table_header_rows",
            frame_ordinal=frame_ordinal,
            frame_name=frame_name,
        )
    if type(table.n_cols) is not int or table.n_cols < 0:
        _raise_exact_structure_error(
            "invalid_exact_table_n_cols",
            frame_ordinal=frame_ordinal,
            frame_name=frame_name,
        )
    if table.header_rows != len(table.header_grid):
        _raise_exact_structure_error(
            "invalid_exact_table_header_grid_height",
            frame_ordinal=frame_ordinal,
            frame_name=frame_name,
        )
    for row_ordinal, row in enumerate(table.header_grid):
        if len(row) != table.n_cols:
            _raise_exact_structure_error(
                "invalid_exact_table_header_row_width",
                frame_ordinal=frame_ordinal,
                frame_name=frame_name,
                row_ordinal=row_ordinal,
            )
        for column_ordinal, cell in enumerate(row):
            if not isinstance(cell, str):
                _raise_exact_structure_error(
                    "invalid_exact_table_header_cell",
                    frame_ordinal=frame_ordinal,
                    frame_name=frame_name,
                    row_ordinal=row_ordinal,
                    column_ordinal=column_ordinal,
                )
    for row_ordinal, row in enumerate(table.data):
        if len(row) != table.n_cols:
            _raise_exact_structure_error(
                "invalid_exact_table_data_row_width",
                frame_ordinal=frame_ordinal,
                frame_name=frame_name,
                row_ordinal=row_ordinal,
            )


def _raise_cell_error(
    *,
    carrier_role: _CarrierRole,
    frame_ordinal: int,
    frame_name: str,
    row_ordinal: int,
    column_ordinal: int,
) -> None:
    raise OrdinaryStructureAdmissionError(
        kind="unsupported_scalar_carrier",
        carrier_role=carrier_role,
        frame_ordinal=frame_ordinal,
        frame_name=frame_name,
        row_ordinal=row_ordinal,
        column_ordinal=column_ordinal,
    ) from None


def _admit_dataframe_cells(
    frame: pd.DataFrame,
    *,
    frame_ordinal: int,
    frame_name: str,
) -> None:
    for row_ordinal in range(frame.shape[0]):
        for column_ordinal in range(frame.shape[1]):
            try:
                admit_ordinary_scalar(frame.iat[row_ordinal, column_ordinal])
            except OrdinaryScalarAdmissionError:
                _raise_cell_error(
                    carrier_role="dataframe",
                    frame_ordinal=frame_ordinal,
                    frame_name=frame_name,
                    row_ordinal=row_ordinal,
                    column_ordinal=column_ordinal,
                )


def _admit_exact_table_cells(
    table: ExactTable,
    *,
    frame_ordinal: int,
    frame_name: str,
) -> None:
    for row_ordinal, row in enumerate(table.data):
        for column_ordinal, cell in enumerate(row):
            try:
                admit_ordinary_scalar(cell)
            except OrdinaryScalarAdmissionError:
                _raise_cell_error(
                    carrier_role="exact_table",
                    frame_ordinal=frame_ordinal,
                    frame_name=frame_name,
                    row_ordinal=row_ordinal,
                    column_ordinal=column_ordinal,
                )


def admit_ordinary_frames(frames: _FramesT) -> _FramesT:
    """Validate one ordinary external Frames candidate and return it unchanged.

    Dispatch, carrier structure, and complete cell admission are separate
    read-only stages.  The reserved ``_meta`` entry is recognized but its value
    is deliberately not inspected until E3 owns that substrate.
    """
    entries = _dispatch_payload_entries(frames)
    for frame_ordinal, frame_name, carrier, role in entries:
        if role == "dataframe":
            _validate_dataframe_structure(
                carrier,
                frame_ordinal=frame_ordinal,
                frame_name=frame_name,
            )
        else:
            _validate_exact_table_structure(
                carrier,
                frame_ordinal=frame_ordinal,
                frame_name=frame_name,
            )
    for frame_ordinal, frame_name, carrier, role in entries:
        if role == "dataframe":
            _admit_dataframe_cells(
                carrier,
                frame_ordinal=frame_ordinal,
                frame_name=frame_name,
            )
        else:
            _admit_exact_table_cells(
                carrier,
                frame_ordinal=frame_ordinal,
                frame_name=frame_name,
            )
    return frames


__all__ = ["OrdinaryStructureAdmissionError", "admit_ordinary_frames"]
