from __future__ import annotations

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
