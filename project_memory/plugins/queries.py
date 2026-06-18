from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import pandas as pd


def _frame_or_empty(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    frame = frames.get(name)
    if isinstance(frame, pd.DataFrame):
        return frame.copy()
    return pd.DataFrame()


def _as_string_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[column].fillna("").astype(str)


def _stable_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = ""
    return out.loc[:, columns]


def _json_safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    def _json_safe_value(value: Any) -> Any:
        if value is None or pd.isna(value):
            return ""
        if isinstance(value, pd.Timestamp):
            return str(value)
        if hasattr(value, "isoformat") and not isinstance(value, str):
            try:
                return value.isoformat()
            except TypeError:
                pass
        return value

    out = df.copy()
    for col in out.columns:
        out[col] = out[col].map(_json_safe_value)
    return out


def current_findings(frames: Mapping[str, Any], *, source: str = "findings") -> dict[str, pd.DataFrame]:
    findings = _frame_or_empty(frames, source)
    if findings.empty:
        out = pd.DataFrame(columns=[
            "id", "severity", "topic", "status", "current_relevance",
            "affected_area", "target_type", "target_id", "summary", "review_id", "detail",
        ])
        return {**dict(frames), "current_findings": _json_safe_frame(out)}

    status = _as_string_series(findings, "status")
    relevance = _as_string_series(findings, "current_relevance")
    mask = relevance.ne("historical") & ~status.isin(["resolved", "superseded", "historical"])
    filtered = findings.loc[mask].copy()
    columns = [
        "id", "severity", "topic", "status", "current_relevance",
        "affected_area", "target_type", "target_id", "summary", "review_id", "detail",
    ]
    return {**dict(frames), "current_findings": _json_safe_frame(_stable_columns(filtered, columns))}


def ftr_dependency_edges(frames: Mapping[str, Any], *, source: str = "ftr_dependencies") -> dict[str, pd.DataFrame]:
    deps = _frame_or_empty(frames, source)
    if deps.empty:
        out = pd.DataFrame(columns=[
            "id", "source_ftr_id", "relation", "target_ftr_id", "status", "note",
        ])
        return {**dict(frames), "ftr_dependency_edges": _json_safe_frame(out)}

    status = _as_string_series(deps, "status")
    filtered = deps.loc[status.eq("active")].copy()
    columns = ["id", "source_ftr_id", "relation", "target_ftr_id", "status", "note"]
    return {**dict(frames), "ftr_dependency_edges": _json_safe_frame(_stable_columns(filtered, columns))}


def ftr_blockers(frames: Mapping[str, Any], *, ftrs: str = "ftrs", ftr_dependencies: str = "ftr_dependencies") -> dict[str, pd.DataFrame]:
    deps = _frame_or_empty(frames, ftr_dependencies)
    ftrs_df = _frame_or_empty(frames, ftrs)

    columns = [
        "source_ftr_id", "source_title", "relation", "target_ftr_id",
        "target_title", "target_status", "target_current_relevance", "note",
    ]
    if deps.empty:
        return {**dict(frames), "ftr_blockers": _json_safe_frame(pd.DataFrame(columns=columns))}

    active = deps.loc[_as_string_series(deps, "status").eq("active")].copy()
    if active.empty:
        return {**dict(frames), "ftr_blockers": _json_safe_frame(pd.DataFrame(columns=columns))}

    source_meta = ftrs_df.loc[:, [c for c in ["id", "title"] if c in ftrs_df.columns]].rename(
        columns={"id": "source_ftr_id", "title": "source_title"}
    )
    target_meta = ftrs_df.loc[:, [c for c in ["id", "title", "status", "current_relevance"] if c in ftrs_df.columns]].rename(
        columns={
            "id": "target_ftr_id",
            "title": "target_title",
            "status": "target_status",
            "current_relevance": "target_current_relevance",
        }
    )

    merged = active.merge(source_meta, on="source_ftr_id", how="left")
    merged = merged.merge(target_meta, on="target_ftr_id", how="left")
    return {**dict(frames), "ftr_blockers": _json_safe_frame(_stable_columns(merged, columns))}


def derived_views_only(
    frames: Mapping[str, Any],
    *,
    names: tuple[str, ...] = ("current_findings", "ftr_dependency_edges", "ftr_blockers"),
) -> dict[str, pd.DataFrame]:
    """Keep only the derived query frames for downstream json_dir export."""
    out: dict[str, pd.DataFrame] = {}
    for name in names:
        frame = frames.get(name)
        if isinstance(frame, pd.DataFrame):
            out[name] = frame.copy()
    return out


def drop_projection_frames(
    frames: Mapping[str, Any],
    *,
    names: tuple[str, ...] = ("concern_signal_matrix",),
    xref_names: tuple[str, ...] = ("concern_signal_threads",),
) -> dict[str, Any]:
    """Drop workbook-only projection frames before canonical JSON staging."""
    out: dict[str, Any] = dict(frames)
    for name in names:
        out.pop(name, None)

    meta = out.get("_meta")
    if isinstance(meta, dict):
        meta = dict(meta)
        xref = meta.get("xref_crosstable")
        if isinstance(xref, dict):
            xref = dict(xref)
            for name in xref_names:
                xref.pop(name, None)
            if xref:
                meta["xref_crosstable"] = xref
            else:
                meta.pop("xref_crosstable", None)
        out["_meta"] = meta

    return out


def copy_frame(frames: Mapping[str, Any], *, source: str, output: str) -> dict[str, Any]:
    """Copy a frame so later recomposition can use it as a stable base."""
    out: dict[str, Any] = dict(frames)
    frame = frames.get(source)
    if isinstance(frame, pd.DataFrame):
        out[output] = frame.copy()
    return out


def finalize_concern_signal_xrefs(
    frames: Mapping[str, Any],
    *,
    frame: str = "concern_signal_xrefs",
    base_frame: str = "__base_concern_signal_xrefs",
    projection_frames: tuple[str, ...] = (
        "concern_signal_matrix",
        "__base_concern_signal_xrefs",
    ),
    xref_names: tuple[str, ...] = ("concern_signal_xrefs",),
) -> dict[str, Any]:
    """Restore deterministic xref IDs/notes and remove workbook-only frames."""
    out: dict[str, Any] = dict(frames)
    current = _frame_or_empty(out, frame)
    base = _frame_or_empty(out, base_frame)

    if not current.empty:
        base_notes = _xref_notes_by_tuple(base)
        rows: list[dict[str, Any]] = []
        for record in current.where(pd.notnull(current), "").to_dict(orient="records"):
            signal_id = str(record.get("signal_id", ""))
            concern_thread_id = str(record.get("concern_thread_id", ""))
            rows.append({
                "id": _concern_signal_xref_id(signal_id, concern_thread_id),
                "signal_id": signal_id,
                "concern_thread_id": concern_thread_id,
                "signal_role": str(record.get("signal_role", "")),
                "notes": base_notes.get((signal_id, concern_thread_id), ""),
            })
        out[frame] = pd.DataFrame(
            rows,
            columns=["id", "signal_id", "concern_thread_id", "signal_role", "notes"],
        )

    for name in projection_frames:
        out.pop(name, None)
    _drop_xref_meta(out, xref_names)
    return out


def _xref_notes_by_tuple(frame: pd.DataFrame) -> dict[tuple[str, str], str]:
    if frame.empty:
        return {}
    notes: dict[tuple[str, str], str] = {}
    clean = frame.where(pd.notnull(frame), "")
    for record in clean.to_dict(orient="records"):
        key = (str(record.get("signal_id", "")), str(record.get("concern_thread_id", "")))
        notes[key] = str(record.get("notes", ""))
    return notes


def _concern_signal_xref_id(signal_id: str, concern_thread_id: str) -> str:
    return f"CTSX-{_safe_id_part(signal_id)}--{_safe_id_part(concern_thread_id)}"


def _safe_id_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")


def _drop_xref_meta(out: dict[str, Any], xref_names: tuple[str, ...]) -> None:
    meta = out.get("_meta")
    if not isinstance(meta, dict):
        return
    meta = dict(meta)
    xref = meta.get("xref_crosstable")
    if isinstance(xref, dict):
        xref = dict(xref)
        for name in xref_names:
            xref.pop(name, None)
        if xref:
            meta["xref_crosstable"] = xref
        else:
            meta.pop("xref_crosstable", None)
    out["_meta"] = meta
