from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_DIR = ROOT / "project_memory" / "canonical"
DERIVED_DIR = ROOT / "project_memory" / "derived"
TEMPLATE_DIR = ROOT / "project_memory" / "templates"
OUTPUT_PATH = ROOT / "docs_generated" / "project_memory" / "current_context.adoc"

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_HISTORIC_RELEVANCE = frozenset({"historic", "historical"})
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


def _active_ftrs(ftrs: list[dict[str, str]]) -> list[dict[str, str]]:
    inactive = {"done", "closed", "resolved", "superseded", "historical", "wontfix"}
    rows = [
        row
        for row in ftrs
        if row.get("status", "") not in inactive
        and row.get("current_relevance", "") != "historical"
    ]
    return sorted(
        rows, key=lambda row: (_priority_rank(row.get("priority", "")), row.get("id", ""))
    )


def _current_reviews(reviews: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = [
        row
        for row in reviews
        if row.get("current_relevance", "") in {"current", "partial"}
        or (
            row.get("takeaway_confidence", "") == "high"
            and row.get("current_relevance", "") not in _HISTORIC_RELEVANCE
        )
    ]
    return sorted(rows, key=lambda row: (row.get("date", ""), row.get("id", "")), reverse=True)


def _concern_threads_with_signals(
    concerns: list[dict[str, str]],
    signals: list[dict[str, str]],
    xrefs: list[dict[str, str]],
) -> list[dict[str, Any]]:
    signals_by_id = {row.get("id", ""): row for row in signals}
    signals_by_concern: dict[str, list[dict[str, str]]] = defaultdict(list)
    for xref in xrefs:
        signal = signals_by_id.get(xref.get("signal_id", ""))
        if signal is None:
            continue
        signals_by_concern[xref.get("concern_thread_id", "")].append(
            {
                "signal_id": xref.get("signal_id", ""),
                "signal_role": xref.get("signal_role", ""),
                "signal_date": signal.get("signal_date", ""),
                "source_type": signal.get("source_type", ""),
                "source_id": signal.get("source_id", ""),
                "weight": signal.get("weight", ""),
                "summary": signal.get("summary", ""),
                "notes": xref.get("notes", "") or signal.get("notes", ""),
            }
        )

    enriched: list[dict[str, Any]] = []
    for concern in concerns:
        row: dict[str, Any] = dict(concern)
        linked = signals_by_concern.get(concern.get("id", ""), [])
        row["signals"] = sorted(
            linked,
            key=lambda signal: (
                _reverse_date_rank(signal.get("signal_date", "")),
                _priority_rank(signal.get("weight", "")),
                signal.get("signal_id", ""),
            ),
        )
        enriched.append(row)
    return sorted(enriched, key=_concern_rank)


def _diagnostics(
    *,
    ftrs: list[dict[str, str]],
    ftr_dependencies: list[dict[str, str]],
    concerns: list[dict[str, str]],
    signals: list[dict[str, str]],
    concern_signal_xrefs: list[dict[str, str]],
) -> dict[str, Any]:
    ftr_ids = {row.get("id", "") for row in ftrs}
    concern_ids = {row.get("id", "") for row in concerns}
    signal_ids = {row.get("id", "") for row in signals}

    missing_signals = [
        row for row in concern_signal_xrefs if row.get("signal_id", "") not in signal_ids
    ]
    missing_concerns = [
        row for row in concern_signal_xrefs if row.get("concern_thread_id", "") not in concern_ids
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
        "missing_concern_signal_refs": missing_signals,
        "missing_concern_thread_refs": missing_concerns,
        "missing_ftr_dependency_refs": missing_ftr_refs,
        "has_warnings": bool(missing_signals or missing_concerns or missing_ftr_refs),
    }


def build_render_context() -> dict[str, Any]:
    current_findings = _read_rows(DERIVED_DIR / "current_findings.json")
    blockers = _read_rows(DERIVED_DIR / "ftr_blockers.json")
    edges = _read_rows(DERIVED_DIR / "ftr_dependency_edges.json")
    concerns = _read_rows(CANONICAL_DIR / "concern_threads.json")
    concern_signals = _read_rows(CANONICAL_DIR / "concern_signals.json")
    concern_signal_xrefs = _read_rows(CANONICAL_DIR / "concern_signal_xrefs.json")
    ftrs = _read_rows(CANONICAL_DIR / "ftrs.json")
    ftr_dependencies = _read_rows(CANONICAL_DIR / "ftr_dependencies.json")
    reviews = _read_rows(CANONICAL_DIR / "reviews.json")

    diagnostics = _diagnostics(
        ftrs=ftrs,
        ftr_dependencies=ftr_dependencies,
        concerns=concerns,
        signals=concern_signals,
        concern_signal_xrefs=concern_signal_xrefs,
    )
    return {
        "title": "Current Project Memory Context",
        "generated_from": "project_memory/canonical",
        "concern_threads": _concern_threads_with_signals(
            concerns,
            concern_signals,
            concern_signal_xrefs,
        ),
        "current_findings": current_findings,
        "active_ftrs": _active_ftrs(ftrs),
        "ftr_blockers": blockers,
        "ftr_dependency_edges": edges,
        "reviews": _current_reviews(reviews),
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
