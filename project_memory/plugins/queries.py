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


def release_note_candidates(
    frames: Mapping[str, Any],
    *,
    signals: str = "concern_events",
    xrefs: str = "concern_event_xrefs",
    default_section: str = "Internal architecture and project memory",
    default_audience: str = "maintainer",
    default_status: str = "candidate",
) -> dict[str, Any]:
    """Derive release-note candidates from curated activity signals (source_type='activity' or SIG-ACT-* id)."""
    sigs = _frame_or_empty(frames, signals)
    xrefs_df = _frame_or_empty(frames, xrefs)

    output_columns = [
        "id", "event_id", "event_date", "source_type", "source_id",
        "commit_refs", "weight", "section", "audience", "status",
        "summary", "notes", "linked_concern_ids",
    ]

    if sigs.empty:
        return {**dict(frames), "release_note_candidates": _json_safe_frame(pd.DataFrame(columns=output_columns))}

    source_type_col = _as_string_series(sigs, "source_type")
    id_col = _as_string_series(sigs, "id")
    activity = sigs.loc[source_type_col.eq("activity") | id_col.str.startswith("SIG-ACT-")].copy()

    if activity.empty:
        return {**dict(frames), "release_note_candidates": _json_safe_frame(pd.DataFrame(columns=output_columns))}

    orig_ids = _as_string_series(activity, "id")

    # Resolve linked concern IDs from xrefs via a dict lookup (avoids merge column collisions)
    if not xrefs_df.empty and "event_id" in xrefs_df.columns and "concern_id" in xrefs_df.columns:
        grouped = (
            xrefs_df.groupby("event_id", sort=False)["concern_id"]
            .apply(lambda s: ", ".join(sorted(s.dropna().astype(str).tolist())))
        )
        activity["linked_concern_ids"] = orig_ids.map(grouped).fillna("")
    else:
        activity["linked_concern_ids"] = ""

    def _default(col: str, default: str) -> pd.Series:
        if col in activity.columns:
            s = activity[col].fillna("").astype(str)
            return s.where(s != "", default)
        return pd.Series([default] * len(activity), index=activity.index, dtype="object")

    activity["section"] = _default("release_note_section", default_section)
    activity["audience"] = _default("release_note_audience", default_audience)
    activity["status"] = _default("release_note_status", default_status)

    if "release_note_summary" in activity.columns:
        rn = activity["release_note_summary"].fillna("").astype(str)
        activity["summary"] = rn.where(rn != "", _as_string_series(activity, "summary"))
    else:
        activity["summary"] = _as_string_series(activity, "summary")

    activity["event_id"] = orig_ids
    activity["id"] = "RNC-" + orig_ids

    result = _json_safe_frame(_stable_columns(activity, output_columns))
    result = result.sort_values(["event_date", "event_id"], ascending=[False, True]).reset_index(drop=True)
    return {**dict(frames), "release_note_candidates": result}


def _parse_commit_refs(value: str) -> list[str]:
    """Split a comma-or-semicolon-separated commit ref string; normalise each hash to 7 chars."""
    if not value.strip():
        return []
    parts = [h.strip() for h in value.replace(";", ",").split(",") if h.strip()]
    return [p[:7] for p in parts if len(p) >= 6]


def event_ftr_links(
    frames: Mapping[str, Any],
    *,
    events: str = "concern_events",
    xrefs: str = "concern_event_xrefs",
    ftrs: str = "ftrs",
) -> dict[str, Any]:
    """Link concern events to FTRs via shared commit references."""
    events_df = _frame_or_empty(frames, events)
    xrefs_df = _frame_or_empty(frames, xrefs)
    ftrs_df = _frame_or_empty(frames, ftrs)

    output_columns = [
        "event_id", "concern_ids", "ftr_id", "match_field",
        "matched_commit", "ftr_summary", "event_summary",
    ]

    if events_df.empty or ftrs_df.empty:
        return {**dict(frames), "event_ftr_links": _json_safe_frame(pd.DataFrame(columns=output_columns))}

    # event_id → comma-separated concern_ids
    concern_map: dict[str, str] = {}
    if not xrefs_df.empty and "event_id" in xrefs_df.columns and "concern_id" in xrefs_df.columns:
        clean = xrefs_df.where(xrefs_df.notna(), "")
        for eid, grp in clean.groupby("event_id"):
            ids = sorted(grp["concern_id"].astype(str).unique().tolist())
            concern_map[str(eid)] = ", ".join(i for i in ids if i)

    # normalised_commit → [(ftr_id, match_field, ftr_summary)]
    commit_to_ftrs: dict[str, list[tuple[str, str, str]]] = {}
    for ftr_row in ftrs_df.where(ftrs_df.notna(), "").to_dict(orient="records"):
        ftr_id = str(ftr_row.get("id", ""))
        ftr_summary = str(ftr_row.get("summary", ""))
        for field in ("created_commit", "implementation_commits", "review_commits"):
            for h in _parse_commit_refs(str(ftr_row.get(field, ""))):
                commit_to_ftrs.setdefault(h, []).append((ftr_id, field, ftr_summary))

    rows: list[dict[str, str]] = []
    for event_row in events_df.where(events_df.notna(), "").to_dict(orient="records"):
        event_id = str(event_row.get("id", ""))
        event_summary = str(event_row.get("summary", ""))
        concern_ids = concern_map.get(event_id, "")
        for h in _parse_commit_refs(str(event_row.get("commit_refs", ""))):
            for ftr_id, match_field, ftr_summary in commit_to_ftrs.get(h, []):
                rows.append({
                    "event_id": event_id,
                    "concern_ids": concern_ids,
                    "ftr_id": ftr_id,
                    "match_field": match_field,
                    "matched_commit": h,
                    "ftr_summary": ftr_summary,
                    "event_summary": event_summary,
                })

    result = pd.DataFrame(rows, columns=output_columns) if rows else pd.DataFrame(columns=output_columns)
    result = result.drop_duplicates().sort_values(["event_id", "ftr_id"], ignore_index=True)
    return {**dict(frames), "event_ftr_links": _json_safe_frame(result)}


def derived_views_only(
    frames: Mapping[str, Any],
    *,
    names: tuple[str, ...] = (
        "current_findings", "ftr_dependency_edges", "ftr_blockers",
        "release_note_candidates", "event_ftr_links",
    ),
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
    names: tuple[str, ...] = ("concern_event_matrix",),
    xref_names: tuple[str, ...] = ("concern_event_threads",),
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


def enrich_concern_event_matrix(
    frames: Mapping[str, Any],
    *,
    matrix: str = "concern_event_matrix",
    signals: str = "concern_events",
    context_columns: tuple[str, ...] = ("event_date", "source_type", "summary"),
) -> dict[str, Any]:
    """Add display-only event context to the concern-event matrix."""
    out: dict[str, Any] = dict(frames)
    matrix_frame = _frame_or_empty(frames, matrix)
    signals_frame = _frame_or_empty(frames, signals)
    if matrix_frame.empty or signals_frame.empty or "event_id" not in matrix_frame.columns:
        return out

    context = _stable_columns(signals_frame.rename(columns={"id": "event_id"}), [
        "event_id",
        *context_columns,
    ])
    enriched = matrix_frame.merge(context, on="event_id", how="left")
    ordered_columns = [
        "event_id",
        *context_columns,
        *[col for col in matrix_frame.columns if col != "event_id"],
    ]
    out[matrix] = _json_safe_frame(_stable_columns(enriched, ordered_columns))
    return out


def strip_concern_event_matrix_context(
    frames: Mapping[str, Any],
    *,
    matrix: str = "concern_event_matrix",
    context_columns: tuple[str, ...] = ("event_date", "source_type", "summary"),
) -> dict[str, Any]:
    """Remove display-only matrix context columns before xref expansion."""
    out: dict[str, Any] = dict(frames)
    matrix_frame = _frame_or_empty(frames, matrix)
    if matrix_frame.empty:
        return out
    drop_columns = [col for col in context_columns if col in matrix_frame.columns]
    out[matrix] = matrix_frame.drop(columns=drop_columns)
    return out


def finalize_concern_event_xrefs(
    frames: Mapping[str, Any],
    *,
    frame: str = "concern_event_xrefs",
    base_frame: str = "__base_concern_event_xrefs",
    projection_frames: tuple[str, ...] = (
        "concern_event_matrix",
        "__base_concern_event_xrefs",
    ),
    xref_names: tuple[str, ...] = ("concern_event_xrefs",),
) -> dict[str, Any]:
    """Restore deterministic xref IDs/notes and remove workbook-only frames."""
    out: dict[str, Any] = dict(frames)
    current = _frame_or_empty(out, frame)
    base = _frame_or_empty(out, base_frame)

    if not current.empty:
        base_notes = _xref_notes_by_tuple(base)
        rows: list[dict[str, Any]] = []
        for record in current.where(pd.notnull(current), "").to_dict(orient="records"):
            event_id = str(record.get("event_id", ""))
            concern_id = str(record.get("concern_id", ""))
            rows.append({
                "id": _concern_event_xref_id(event_id, concern_id),
                "event_id": event_id,
                "concern_id": concern_id,
                "event_role": str(record.get("event_role", "")),
                "notes": base_notes.get((event_id, concern_id), ""),
            })
        out[frame] = pd.DataFrame(
            rows,
            columns=["id", "event_id", "concern_id", "event_role", "notes"],
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
        key = (str(record.get("event_id", "")), str(record.get("concern_id", "")))
        notes[key] = str(record.get("notes", ""))
    return notes


def _concern_event_xref_id(event_id: str, concern_id: str) -> str:
    return f"CTSX-{_safe_id_part(event_id)}--{_safe_id_part(concern_id)}"


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
