from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from tools.domain_contracts.check_contracts import BOOLEAN_FIELDS, sorted_lifecycle_phases

LIFECYCLE_MATRIX_FRAME = "transformation_lifecycle_matrix"
LIFECYCLE_NOTE_DEFAULT_ROLE = "open_question"
LIFECYCLE_NOTE_DEFAULT_STATUS = "draft_inferred"


def _coerce_bool(value: Any) -> bool | Any:
    if isinstance(value, bool):
        return value
    text = "" if value is None else str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return value


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _records(frame: Any) -> list[dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame):
        return []
    return frame.fillna("").to_dict(orient="records")


def _lifecycle_note_id(transformation_id: str, lifecycle_phase_id: str) -> str:
    trans_slug = transformation_id.removeprefix("TRANS-")
    phase_slug = lifecycle_phase_id.removeprefix("LIFE-")
    return f"TLIFE-{trans_slug}--{phase_slug}"


def _lifecycle_phase_ids(frames: Mapping[str, Any]) -> list[str]:
    phases = sorted_lifecycle_phases(_records(frames.get("lifecycle_phase")))
    return [str(row["id"]) for row in phases if row.get("id")]


def _transformation_rows(frames: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _records(frames.get("transformations"))
    return sorted(rows, key=lambda row: str(row.get("id", "")))


def add_lifecycle_matrix_frame(frames: Mapping[str, Any]) -> dict[str, Any]:
    """Add an editable transformation/lifecycle matrix sheet for workbook review."""
    out: dict[str, Any] = {
        name: frame.copy() if isinstance(frame, pd.DataFrame) else frame
        for name, frame in frames.items()
    }
    transformation_rows = _transformation_rows(out)
    lifecycle_phase_ids = _lifecycle_phase_ids(out)
    notes_by_pair = {
        (str(row.get("transformation_id", "")), str(row.get("lifecycle_phase_id", ""))): _cell_text(
            row.get("details")
        )
        for row in _records(out.get("transformation_lifecycle_notes"))
    }

    rows: list[dict[str, Any]] = []
    for transformation in transformation_rows:
        transformation_id = str(transformation.get("id", ""))
        row: dict[str, Any] = {
            "transformation_id": transformation_id,
            "transformation_name": str(transformation.get("name", "")),
        }
        for phase_id in lifecycle_phase_ids:
            row[phase_id] = notes_by_pair.get((transformation_id, phase_id), "")
        rows.append(row)

    out[LIFECYCLE_MATRIX_FRAME] = pd.DataFrame(
        rows,
        columns=["transformation_id", "transformation_name", *lifecycle_phase_ids],
    )
    return out


def _build_lifecycle_notes_from_matrix(frames: Mapping[str, Any]) -> pd.DataFrame | None:
    matrix = frames.get(LIFECYCLE_MATRIX_FRAME)
    if not isinstance(matrix, pd.DataFrame):
        return None

    phase_ids = _lifecycle_phase_ids(frames)
    existing_rows = _records(frames.get("transformation_lifecycle_notes"))
    existing_by_pair = {
        (str(row.get("transformation_id", "")), str(row.get("lifecycle_phase_id", ""))): row
        for row in existing_rows
    }

    matrix_details: dict[tuple[str, str], str] = {}
    for matrix_row in matrix.fillna("").to_dict(orient="records"):
        transformation_id = _cell_text(matrix_row.get("transformation_id"))
        if not transformation_id:
            continue
        for phase_id in phase_ids:
            details = _cell_text(matrix_row.get(phase_id))
            if not details:
                continue
            matrix_details[(transformation_id, phase_id)] = details

    rows: list[dict[str, Any]] = []
    emitted: set[tuple[str, str]] = set()
    for existing in existing_rows:
        pair = (
            str(existing.get("transformation_id", "")),
            str(existing.get("lifecycle_phase_id", "")),
        )
        details = matrix_details.get(pair)
        if not details:
            continue
        rows.append(
            {
                "id": existing.get("id") or _lifecycle_note_id(pair[0], pair[1]),
                "transformation_id": pair[0],
                "lifecycle_phase_id": pair[1],
                "role": existing.get("role") or LIFECYCLE_NOTE_DEFAULT_ROLE,
                "details": details,
                "source_refs": existing.get("source_refs") or "",
                "status": existing.get("status") or LIFECYCLE_NOTE_DEFAULT_STATUS,
            }
        )
        emitted.add(pair)

    for pair, details in matrix_details.items():
        if pair in emitted:
            continue
        rows.append(
            {
                "id": _lifecycle_note_id(pair[0], pair[1]),
                "transformation_id": pair[0],
                "lifecycle_phase_id": pair[1],
                "role": LIFECYCLE_NOTE_DEFAULT_ROLE,
                "details": details,
                "source_refs": "",
                "status": LIFECYCLE_NOTE_DEFAULT_STATUS,
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "id",
            "transformation_id",
            "lifecycle_phase_id",
            "role",
            "details",
            "source_refs",
            "status",
        ],
    )


def normalize_reimported_contract_frames(frames: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize spreadsheet carrier values before writing staging JSON."""
    out: dict[str, Any] = {
        name: frame.copy() if isinstance(frame, pd.DataFrame) else frame
        for name, frame in frames.items()
        if name not in {"_meta", LIFECYCLE_MATRIX_FRAME}
    }
    lifecycle_notes = _build_lifecycle_notes_from_matrix(frames)
    if lifecycle_notes is not None:
        out["transformation_lifecycle_notes"] = lifecycle_notes

    for frame_name, fields in BOOLEAN_FIELDS.items():
        frame = out.get(frame_name)
        if not isinstance(frame, pd.DataFrame):
            continue
        for field in fields:
            if field in frame.columns:
                frame[field] = frame[field].map(_coerce_bool)
    return out
