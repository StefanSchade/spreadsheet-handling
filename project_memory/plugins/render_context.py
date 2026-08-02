from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_DIR = ROOT / "project_memory" / "canonical"
DERIVED_DIR = ROOT / "project_memory" / "derived"
TEMPLATE_DIR = ROOT / "project_memory" / "templates"
OUTPUT_PATH = ROOT / "docs_generated" / "project_memory" / "current_context.adoc"
RELEASE_NOTE_CANDIDATES_PATH = ROOT / "docs_generated" / "project_memory" / "release_note_candidates.adoc"

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
# Lifecycle words that mean an FTR is no longer active work. Matched as whole
# words so compound statuses such as "done (accepted)" or "superseded (design
# absorbed)" are correctly recognised as inactive, while active statuses such as
# "implemented" or "new (active)" are kept.
_INACTIVE_STATUS_WORDS = frozenset(
    {"done", "closed", "resolved", "superseded", "historical", "wontfix"}
)
_CURRENT_REVIEW_RELEVANCE = frozenset({"current", "partial"})
# Per-concern cap on the number of most-recent linked events rendered in the
# default context. Older events stay in canonical memory and remain discoverable
# there; the concern's current_summary carries the durable posture.
_MAX_CONCERN_EVENTS = 12
CONCERN_STATUS_ORDER = {
    ("active", "doing_now"): 0,
    ("active", ""): 1,
    ("watching", ""): 2,
}


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    rows: list[dict[str, str]] = []
    for item in data:
        if isinstance(item, dict):
            rows.append({str(k): "" if v is None else str(v) for k, v in item.items()})
    return rows


def _escape_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", r"\|").replace("\n", " ").replace("\r", " ")


def _priority_rank(value: str) -> int:
    return PRIORITY_ORDER.get(value, 99)


def _reverse_date_rank(value: str) -> str:
    # ISO dates sort lexicographically; invert digits for descending date order in tuple keys.
    return "".join(str(9 - int(char)) if char.isdigit() else char for char in value)


def _concern_rank(row: dict[str, Any]) -> tuple[int, int, str]:
    status = str(row.get("status", ""))
    posture = str(row.get("posture", ""))
    status_rank = CONCERN_STATUS_ORDER.get((status, posture))
    if status_rank is None:
        status_rank = CONCERN_STATUS_ORDER.get((status, ""), 99)
    return (status_rank, _priority_rank(str(row.get("priority", ""))), str(row.get("id", "")))


def _status_is_inactive(status: str) -> bool:
    words = re.findall(r"[a-z0-9]+", status.lower())
    return any(word in _INACTIVE_STATUS_WORDS for word in words)


def _active_ftrs(ftrs: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = [
        row
        for row in ftrs
        if not _status_is_inactive(row.get("status", ""))
        and row.get("current_relevance", "") != "historical"
    ]
    return sorted(
        rows, key=lambda row: (_priority_rank(row.get("priority", "")), row.get("id", ""))
    )


def _review_sets_grouped(
    review_sets: list[dict[str, str]],
    reviews: list[dict[str, str]],
) -> list[dict[str, Any]]:
    reviews_by_set: dict[str, list[dict[str, str]]] = defaultdict(list)
    for review in reviews:
        rs_id = review.get("review_set_id", "")
        if rs_id:
            reviews_by_set[rs_id].append(review)

    enriched: list[dict[str, Any]] = []
    for rs in sorted(review_sets, key=lambda r: (r.get("category", ""), r.get("id", ""))):
        row: dict[str, Any] = dict(rs)
        all_reviews = sorted(
            reviews_by_set.get(rs.get("id", ""), []),
            key=lambda r: (r.get("date", ""), r.get("id", "")),
        )
        # The default context surfaces only currently relevant reviews per set;
        # routine historical acceptance reviews are kept discoverable through the
        # set anchor and a count rather than rendered in full. Full detail lives
        # in the review documents under docs/cold_storage/reviews/.
        current = [
            r
            for r in all_reviews
            if r.get("current_relevance", "") in _CURRENT_REVIEW_RELEVANCE
        ]
        row["reviews"] = current
        row["historical_review_count"] = len(all_reviews) - len(current)
        enriched.append(row)
    return enriched


def _decisions(decisions: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(decisions, key=lambda row: row.get("id", ""))


def _concerns_with_events(
    concerns: list[dict[str, str]],
    events: list[dict[str, str]],
    xrefs: list[dict[str, str]],
) -> list[dict[str, Any]]:
    events_by_id = {row.get("id", ""): row for row in events}
    events_by_concern: dict[str, list[dict[str, str]]] = defaultdict(list)
    for xref in xrefs:
        event = events_by_id.get(xref.get("event_id", ""))
        if event is None:
            continue
        events_by_concern[xref.get("concern_id", "")].append(
            {
                "event_id": xref.get("event_id", ""),
                "event_role": xref.get("event_role", ""),
                "event_date": event.get("event_date", ""),
                "source_type": event.get("source_type", ""),
                "source_id": event.get("source_id", ""),
                "weight": event.get("weight", ""),
                "summary": event.get("summary", ""),
                "notes": xref.get("notes", "") or event.get("notes", ""),
            }
        )

    enriched: list[dict[str, Any]] = []
    for concern in concerns:
        row: dict[str, Any] = dict(concern)
        linked = events_by_concern.get(concern.get("id", ""), [])
        ordered = sorted(
            linked,
            key=lambda event: (
                _reverse_date_rank(event.get("event_date", "")),
                _priority_rank(event.get("weight", "")),
                event.get("event_id", ""),
            ),
        )
        # Render only the most recent events per concern in the default context;
        # keep the rest discoverable via the count and canonical memory.
        row["events"] = ordered[:_MAX_CONCERN_EVENTS]
        row["older_event_count"] = max(len(ordered) - _MAX_CONCERN_EVENTS, 0)
        enriched.append(row)
    return sorted(enriched, key=_concern_rank)


def _diagnostics(
    *,
    ftrs: list[dict[str, str]],
    ftr_dependencies: list[dict[str, str]],
    concerns: list[dict[str, str]],
    events: list[dict[str, str]],
    concern_event_xrefs: list[dict[str, str]],
) -> dict[str, Any]:
    ftr_ids = {row.get("id", "") for row in ftrs}
    concern_ids = {row.get("id", "") for row in concerns}
    event_ids = {row.get("id", "") for row in events}

    missing_events = [
        row for row in concern_event_xrefs if row.get("event_id", "") not in event_ids
    ]
    missing_concerns = [
        row for row in concern_event_xrefs if row.get("concern_id", "") not in concern_ids
    ]
    missing_ftr_refs = [
        {
            **row,
            "missing_source": row.get("source_ftr_id", "") not in ftr_ids,
            "missing_target": row.get("target_ftr_id", "") not in ftr_ids,
        }
        for row in ftr_dependencies
        if row.get("source_ftr_id", "") not in ftr_ids
        or row.get("target_ftr_id", "") not in ftr_ids
    ]

    return {
        "missing_concern_event_refs": missing_events,
        "missing_concern_refs": missing_concerns,
        "missing_ftr_dependency_refs": missing_ftr_refs,
        "has_warnings": bool(missing_events or missing_concerns or missing_ftr_refs),
    }


def build_render_context() -> dict[str, Any]:
    current_findings = _read_rows(DERIVED_DIR / "current_findings.json")
    blockers = _read_rows(DERIVED_DIR / "ftr_blockers.json")
    edges = _read_rows(DERIVED_DIR / "ftr_dependency_edges.json")
    event_ftr_links = _read_rows(DERIVED_DIR / "event_ftr_links.json")
    concerns = _read_rows(CANONICAL_DIR / "concerns.json")
    concern_events = _read_rows(CANONICAL_DIR / "concern_events.json")
    concern_event_xrefs = _read_rows(CANONICAL_DIR / "concern_event_xrefs.json")
    ftrs = _read_rows(CANONICAL_DIR / "ftrs.json")
    ftr_dependencies = _read_rows(CANONICAL_DIR / "ftr_dependencies.json")
    review_sets = _read_rows(CANONICAL_DIR / "review_sets.json")
    reviews = _read_rows(CANONICAL_DIR / "reviews.json")
    decisions = _read_rows(CANONICAL_DIR / "decisions.json")

    diagnostics = _diagnostics(
        ftrs=ftrs,
        ftr_dependencies=ftr_dependencies,
        concerns=concerns,
        events=concern_events,
        concern_event_xrefs=concern_event_xrefs,
    )
    return {
        "title": "Current Project Memory Context",
        "generated_from": "project_memory/canonical",
        "concerns": _concerns_with_events(
            concerns,
            concern_events,
            concern_event_xrefs,
        ),
        "current_findings": current_findings,
        "decisions": _decisions(decisions),
        "active_ftrs": _active_ftrs(ftrs),
        "ftr_blockers": blockers,
        "ftr_dependency_edges": edges,
        "review_sets": _review_sets_grouped(review_sets, reviews),
        "event_ftr_link_count": len(event_ftr_links),
        "diagnostics": diagnostics,
    }


def _template_environment() -> Any:
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError as exc:  # pragma: no cover - exercised only without optional extra.
        raise ImportError(
            "Jinja2 is required for project_memory context rendering. "
            "Install the optional project-memory tooling extra with: "
            "pip install -e '.[project-memory]'"
        ) from exc

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["adoc_cell"] = _escape_cell
    return env


def _group_by_section(
    candidates: list[dict[str, str]],
) -> list[tuple[str, list[dict[str, str]]]]:
    sections: dict[str, list[dict[str, str]]] = {}
    for row in candidates:
        sections.setdefault(row.get("section", ""), []).append(row)
    return [
        (section, sorted(rows, key=lambda r: r.get("event_date", ""), reverse=True))
        for section, rows in sorted(sections.items())
    ]


def build_release_note_context() -> dict[str, Any]:
    candidates = _read_rows(DERIVED_DIR / "release_note_candidates.json")
    return {
        "title": "Release Note Candidates",
        "candidates_by_section": _group_by_section(candidates),
        "candidates": candidates,
    }


def render_release_note_candidates(
    output_path: Path | str = RELEASE_NOTE_CANDIDATES_PATH,
) -> Path:
    output = Path(output_path)
    context = build_release_note_context()
    template = _template_environment().get_template("release_note_candidates.adoc.j2")
    rendered = template.render(**context)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(rendered.rstrip() + "\n")
    return output


def render_current_context(output_path: Path | str = OUTPUT_PATH) -> Path:
    output = Path(output_path)
    context = build_render_context()
    template = _template_environment().get_template("current_context.adoc.j2")
    rendered = template.render(**context)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(rendered.rstrip() + "\n")
    return output


if __name__ == "__main__":
    render_current_context()
    render_release_note_candidates()
