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


def finding_assessment_heatmap(
    frames: Mapping[str, Any],
    *,
    findings_source: str = "findings",
    mappings_source: str = "assessment_scale_mappings",
    normalized_scale: str = "impact_0_5",
) -> dict[str, Any]:
    """Join finding severity to normalized impact values via assessment_scale_mappings."""
    from project_memory.plugins.assessment_scale import build_lookup_index

    findings = _frame_or_empty(frames, findings_source)
    mappings_frame = _frame_or_empty(frames, mappings_source)

    output_columns = [
        "id", "severity", "topic", "status", "current_relevance",
        "normalized_scale", "normalized_value", "normalized_label", "mapping_status",
    ]

    if findings.empty:
        return {**dict(frames), "finding_assessment_heatmap": _json_safe_frame(pd.DataFrame(columns=output_columns))}

    mappings_list: list[Any] = (
        mappings_frame.where(mappings_frame.notna(), None).to_dict(orient="records")
        if not mappings_frame.empty
        else []
    )
    index = build_lookup_index(mappings_list)

    rows: list[dict[str, Any]] = []
    for record in findings.where(findings.notna(), "").to_dict(orient="records"):
        finding_id = str(record.get("id", ""))
        severity = str(record.get("severity", ""))
        mapping = index.get(("finding", "severity", severity, normalized_scale))
        if mapping is not None:
            rows.append({
                "id": finding_id,
                "severity": severity,
                "topic": str(record.get("topic", "")),
                "status": str(record.get("status", "")),
                "current_relevance": str(record.get("current_relevance", "")),
                "normalized_scale": normalized_scale,
                "normalized_value": mapping.get("normalized_value", ""),
                "normalized_label": str(mapping.get("normalized_label", "")),
                "mapping_status": "mapped",
            })
        else:
            rows.append({
                "id": finding_id,
                "severity": severity,
                "topic": str(record.get("topic", "")),
                "status": str(record.get("status", "")),
                "current_relevance": str(record.get("current_relevance", "")),
                "normalized_scale": normalized_scale,
                "normalized_value": "",
                "normalized_label": "",
                "mapping_status": "unmapped",
            })

    result = pd.DataFrame(rows, columns=output_columns) if rows else pd.DataFrame(columns=output_columns)
    sort_key = pd.to_numeric(result["normalized_value"], errors="coerce").fillna(-1)
    result = result.iloc[sort_key.sort_values(ascending=False).index].reset_index(drop=True)
    return {**dict(frames), "finding_assessment_heatmap": _json_safe_frame(result)}


# ---------------------------------------------------------------------------
# Concern heatmap
# ---------------------------------------------------------------------------

_RELEVANCE_FACTORS: dict[str, float] = {
    "current": 1.0,
    "partial": 0.6,
    "historical": 0.2,
}
_DEFAULT_RELEVANCE_FACTOR = 0.5
_ACTIVE_RELEVANCE = frozenset({"current"})
_WATCH_RELEVANCE = frozenset({"partial"})
_CLOSED_RELEVANCE = frozenset({"historical"})


def _relevance_factor(current_relevance: str) -> float:
    return _RELEVANCE_FACTORS.get(current_relevance, _DEFAULT_RELEVANCE_FACTOR)


def _finding_to_concern_map(
    events: pd.DataFrame,
    xrefs: pd.DataFrame,
) -> dict[str, list[str]]:
    """Build finding_id -> [concern_ids] via concern_events where source_type='finding'."""
    if events.empty or xrefs.empty:
        return {}
    finding_events = events.loc[_as_string_series(events, "source_type").eq("finding")]
    if finding_events.empty:
        return {}

    event_to_finding: dict[str, str] = {
        str(row.get("id", "")): str(row.get("source_id", ""))
        for row in finding_events.where(finding_events.notna(), "").to_dict(orient="records")
        if row.get("id") and row.get("source_id")
    }

    result: dict[str, list[str]] = {}
    for xref in xrefs.where(xrefs.notna(), "").to_dict(orient="records"):
        event_id = str(xref.get("event_id", ""))
        concern_id = str(xref.get("concern_id", ""))
        finding_id = event_to_finding.get(event_id, "")
        if finding_id and concern_id:
            if finding_id not in result:
                result[finding_id] = []
            if concern_id not in result[finding_id]:
                result[finding_id].append(concern_id)
    return result


def _normalized_impact_value(mapping: dict[str, Any] | None) -> int | None:
    """Return normalized_value as a validated integer in [0, 5], or None.

    Canonical project-memory data is stringly typed at the data boundary.
    This helper casts robustly: accepts int, integer-valued float, or a
    numeric string representing an integer in range.  Non-numeric, fractional,
    or out-of-range values all return None so they are treated as unmapped.
    """
    if mapping is None:
        return None
    raw = mapping.get("normalized_value")
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 0 <= raw <= 5 else None
    if isinstance(raw, float):
        if raw != int(raw):
            return None
        iv = int(raw)
        return iv if 0 <= iv <= 5 else None
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            fv = float(stripped)
        except (ValueError, TypeError):
            return None
        if fv != int(fv):
            return None
        iv = int(fv)
        return iv if 0 <= iv <= 5 else None
    return None


def _concern_interpretation(total_heat: float) -> str:
    if total_heat >= 4.0:
        return "high aggregate impact"
    if total_heat >= 2.0:
        return "moderate aggregate impact"
    if total_heat > 0.0:
        return "low aggregate impact"
    return "no linked finding signals"


def concern_heatmap(
    frames: Mapping[str, Any],
    *,
    findings_source: str = "findings",
    concerns_source: str = "concerns",
    events_source: str = "concern_events",
    xrefs_source: str = "concern_event_xrefs",
    mappings_source: str = "assessment_scale_mappings",
    normalized_scale: str = "impact_0_5",
) -> dict[str, Any]:
    """Aggregate finding impact onto concerns via the impact_0_5 assessment scale.

    Returns two derived frames:
    - 'concern_heatmap': one row per concern with aggregated heat metrics.
    - 'finding_concern_mapping_gaps': findings not linked to any concern, or with unmapped severity.
    """
    from project_memory.plugins.assessment_scale import build_lookup_index

    findings = _frame_or_empty(frames, findings_source)
    concerns = _frame_or_empty(frames, concerns_source)
    events = _frame_or_empty(frames, events_source)
    xrefs = _frame_or_empty(frames, xrefs_source)
    mappings_frame = _frame_or_empty(frames, mappings_source)

    heatmap_columns = [
        "concern_id", "concern_title", "concern_status", "concern_posture", "concern_priority",
        "finding_count", "mapped_finding_count", "unmapped_finding_count",
        "active_heat", "watch_heat", "closed_heat", "total_heat",
        "max_impact", "avg_impact",
        "top_finding_ids", "top_finding_topics", "interpretation_note",
    ]
    gaps_columns = [
        "finding_id", "severity", "topic", "status", "current_relevance",
        "normalized_value", "gap_reason",
    ]

    if concerns.empty:
        return {
            **dict(frames),
            "concern_heatmap": _json_safe_frame(pd.DataFrame(columns=heatmap_columns)),
            "finding_concern_mapping_gaps": _json_safe_frame(pd.DataFrame(columns=gaps_columns)),
        }

    mappings_list: list[Any] = (
        mappings_frame.where(mappings_frame.notna(), None).to_dict(orient="records")
        if not mappings_frame.empty else []
    )
    impact_index = build_lookup_index(mappings_list)
    finding_concern_map = _finding_to_concern_map(events, xrefs)

    concern_findings: dict[str, list[dict[str, Any]]] = {
        str(c.get("id", "")): []
        for c in concerns.where(concerns.notna(), "").to_dict(orient="records")
    }
    gap_rows: list[dict[str, Any]] = []

    if not findings.empty:
        for f in findings.where(findings.notna(), "").to_dict(orient="records"):
            fid = str(f.get("id", ""))
            severity = str(f.get("severity", ""))
            relevance = str(f.get("current_relevance", ""))
            mapping = impact_index.get(("finding", "severity", severity, normalized_scale))
            norm_value = _normalized_impact_value(mapping)

            linked_concerns = finding_concern_map.get(fid, [])
            if not linked_concerns:
                gap_rows.append({
                    "finding_id": fid,
                    "severity": severity,
                    "topic": str(f.get("topic", "")),
                    "status": str(f.get("status", "")),
                    "current_relevance": relevance,
                    "normalized_value": "" if norm_value is None else norm_value,
                    "gap_reason": "no_concern_link",
                })
                continue

            for cid in linked_concerns:
                if cid not in concern_findings:
                    continue
                heat: float | None = (norm_value * _relevance_factor(relevance)) if norm_value is not None else None
                concern_findings[cid].append({
                    "id": fid,
                    "severity": severity,
                    "topic": str(f.get("topic", "")),
                    "status": str(f.get("status", "")),
                    "current_relevance": relevance,
                    "normalized_value": norm_value,
                    "heat": heat,
                    "mapped": norm_value is not None,
                })
                if norm_value is None:
                    gap_rows.append({
                        "finding_id": fid,
                        "severity": severity,
                        "topic": str(f.get("topic", "")),
                        "status": str(f.get("status", "")),
                        "current_relevance": relevance,
                        "normalized_value": "",
                        "gap_reason": "unmapped_severity",
                    })

    heatmap_rows: list[dict[str, Any]] = []
    for concern in concerns.where(concerns.notna(), "").to_dict(orient="records"):
        cid = str(concern.get("id", ""))
        linked = concern_findings.get(cid, [])
        mapped = [item for item in linked if item["mapped"]]

        active_heat = sum(
            item["heat"] for item in mapped if item["current_relevance"] in _ACTIVE_RELEVANCE
        )
        watch_heat = sum(
            item["heat"] for item in mapped
            if item["current_relevance"] in _WATCH_RELEVANCE
            or item["current_relevance"] not in (_ACTIVE_RELEVANCE | _WATCH_RELEVANCE | _CLOSED_RELEVANCE)
        )
        closed_heat = sum(
            item["heat"] for item in mapped if item["current_relevance"] in _CLOSED_RELEVANCE
        )
        total_heat = active_heat + watch_heat + closed_heat

        impacts = [item["normalized_value"] for item in mapped if item["normalized_value"] is not None]
        max_impact: int | str = max(impacts) if impacts else ""
        avg_impact: float | str = round(sum(impacts) / len(impacts), 2) if impacts else ""

        top_3 = sorted(mapped, key=lambda item: (-(item["normalized_value"] or 0), item["id"]))[:3]

        heatmap_rows.append({
            "concern_id": cid,
            "concern_title": str(concern.get("title", "")),
            "concern_status": str(concern.get("status", "")),
            "concern_posture": str(concern.get("posture", "")),
            "concern_priority": str(concern.get("priority", "")),
            "finding_count": len(linked),
            "mapped_finding_count": len(mapped),
            "unmapped_finding_count": len(linked) - len(mapped),
            "active_heat": round(active_heat, 2),
            "watch_heat": round(watch_heat, 2),
            "closed_heat": round(closed_heat, 2),
            "total_heat": round(total_heat, 2),
            "max_impact": max_impact,
            "avg_impact": avg_impact,
            "top_finding_ids": ", ".join(item["id"] for item in top_3),
            "top_finding_topics": ", ".join(item["topic"] for item in top_3),
            "interpretation_note": _concern_interpretation(total_heat),
        })

    heatmap_rows.sort(key=lambda r: (-r["total_heat"], r["concern_id"]))

    gap_rows.sort(key=lambda r: (
        0 if r["current_relevance"] == "current" else (1 if r["current_relevance"] == "partial" else 2),
        -(r["normalized_value"] if isinstance(r["normalized_value"], int) else -1),
        r["finding_id"],
    ))

    heatmap_df = (
        pd.DataFrame(heatmap_rows, columns=heatmap_columns)
        if heatmap_rows else pd.DataFrame(columns=heatmap_columns)
    )
    gaps_df = (
        pd.DataFrame(gap_rows, columns=gaps_columns)
        if gap_rows else pd.DataFrame(columns=gaps_columns)
    )
    return {
        **dict(frames),
        "concern_heatmap": _json_safe_frame(heatmap_df),
        "finding_concern_mapping_gaps": _json_safe_frame(gaps_df),
    }


def derived_views_only(
    frames: Mapping[str, Any],
    *,
    names: tuple[str, ...] = (
        "current_findings", "ftr_dependency_edges", "ftr_blockers",
        "release_note_candidates", "event_ftr_links", "finding_assessment_heatmap",
        "concern_heatmap", "finding_concern_mapping_gaps",
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
