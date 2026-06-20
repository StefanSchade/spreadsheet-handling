"""Generate project_memory health report (derived diagnostic).

Compares canonical memory against extracted Git commit evidence.
Outputs:
  project_memory/derived/memory_health_report.json
  project_memory/derived/memory_health_report.adoc

This report is a diagnostic artifact only. It must not be used to
automatically update canonical data.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_DIR = ROOT / "project_memory" / "canonical"
EXTRACTED_DIR = ROOT / "project_memory" / "extracted"
DERIVED_DIR = ROOT / "project_memory" / "derived"

_CANONICAL_ID_FILES = [
    "ftrs.json",
    "concerns.json",
    "decisions.json",
    "findings.json",
    "releases.json",
    "reviews.json",
    "review_sets.json",
    "ftr_dependencies.json",
]
_FTR_FILE = "ftrs.json"
_EVENTS_FILE = "concern_events.json"
_COMMIT_SIGNALS_FILE = "commit_signals.json"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def _collect_canonical_ids(canonical_dir: Path, files: list[str]) -> set[str]:
    ids: set[str] = set()
    for fname in files:
        for row in _read_json(canonical_dir / fname):
            aid = row.get("id", "")
            if aid:
                ids.add(str(aid))
    return ids


# ---------------------------------------------------------------------------
# Check functions — pure, all inputs injected for testability
# ---------------------------------------------------------------------------

def check_unknown_extracted_artifact_ids(
    commit_signals: list[dict],
    known_ids: set[str],
) -> list[dict]:
    """Artifact IDs in commit evidence that are absent from canonical memory."""
    id_to_commits: dict[str, list[str]] = defaultdict(list)
    for row in commit_signals:
        for aid in row.get("artifact_ids", []):
            id_to_commits[str(aid)].append(str(row.get("short_hash", "")))

    return [
        {
            "artifact_id": aid,
            "commit_count": len(hashes),
            "sample_commits": sorted(hashes)[:5],
        }
        for aid, hashes in sorted(id_to_commits.items())
        if aid not in known_ids
    ]


def check_ambiguous_commit_links(commit_signals: list[dict]) -> list[dict]:
    """Commits where confidence=='ambiguous' (multiple artifact IDs; needs human review)."""
    return [
        {
            "id": str(row.get("id", "")),
            "short_hash": str(row.get("short_hash", "")),
            "commit_date": str(row.get("commit_date", "")),
            "type": str(row.get("type", "")),
            "scope": str(row.get("scope", "")),
            "subject": str(row.get("subject", "")),
            "artifact_ids": list(row.get("artifact_ids", [])),
        }
        for row in commit_signals
        if row.get("confidence") == "ambiguous"
    ]


def check_recent_unlinked_commits(
    commit_signals: list[dict],
    recent_days: int = 14,
    *,
    reference_date: date | None = None,
) -> list[dict]:
    """Commits within `recent_days` that have no artifact ID (confidence=='none')."""
    cutoff = (reference_date or date.today()) - timedelta(days=recent_days)
    cutoff_str = cutoff.isoformat()
    return [
        {
            "id": str(row.get("id", "")),
            "short_hash": str(row.get("short_hash", "")),
            "commit_date": str(row.get("commit_date", "")),
            "type": str(row.get("type", "")),
            "scope": str(row.get("scope", "")),
            "subject": str(row.get("subject", "")),
        }
        for row in commit_signals
        if row.get("confidence") == "none"
        and str(row.get("commit_date", "")) >= cutoff_str
    ]


def check_canonical_events_without_commit_refs(events: list[dict]) -> list[dict]:
    """Activity events in concern_events.json that have no commit_refs.

    Only activity events (source_type=='activity' or id starting with 'SIG-ACT-') are
    checked. Non-activity event types (review_set, finding, release, manual_note) are
    structurally expected to omit commit_refs and are excluded.
    """
    return [
        {
            "id": str(row.get("id", "")),
            "event_date": str(row.get("event_date", "")),
            "source_type": str(row.get("source_type", "")),
            "summary": str(row.get("summary", "")),
        }
        for row in events
        if (
            row.get("source_type") == "activity"
            or str(row.get("id", "")).startswith("SIG-ACT-")
        )
        and not str(row.get("commit_refs", "")).strip()
    ]


def check_known_artifacts_without_commit_evidence(
    ftr_rows: list[dict],
    commit_signals: list[dict],
) -> list[dict]:
    """Canonical FTRs/BUGs not referenced in any commit signal.

    Informational only — some artifacts may legitimately lack direct commit evidence.
    """
    ids_with_evidence: set[str] = set()
    for row in commit_signals:
        ids_with_evidence.update(str(aid) for aid in row.get("artifact_ids", []))

    return [
        {
            "id": str(row.get("id", "")),
            "status": str(row.get("status", "")),
            "priority": str(row.get("priority", "")),
        }
        for row in ftr_rows
        if row.get("id", "") and str(row.get("id", "")) not in ids_with_evidence
    ]


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_health_report(
    canonical_dir: Path = CANONICAL_DIR,
    extracted_dir: Path = EXTRACTED_DIR,
    recent_days: int = 14,
    *,
    reference_date: date | None = None,
) -> dict[str, Any]:
    canonical_files = [f for f in _CANONICAL_ID_FILES if (canonical_dir / f).exists()]
    extracted_files = []
    signals_path = extracted_dir / _COMMIT_SIGNALS_FILE
    if signals_path.exists():
        extracted_files.append(_COMMIT_SIGNALS_FILE)

    known_ids = _collect_canonical_ids(canonical_dir, canonical_files)
    commit_signals = _read_json(signals_path)
    ftr_rows = _read_json(canonical_dir / _FTR_FILE)
    event_rows = _read_json(canonical_dir / _EVENTS_FILE)

    sec_unknown = check_unknown_extracted_artifact_ids(commit_signals, known_ids)
    sec_ambiguous = check_ambiguous_commit_links(commit_signals)
    sec_recent = check_recent_unlinked_commits(
        commit_signals, recent_days, reference_date=reference_date
    )
    sec_no_refs = check_canonical_events_without_commit_refs(event_rows)
    sec_no_evidence = check_known_artifacts_without_commit_evidence(ftr_rows, commit_signals)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "canonical_files": canonical_files,
            "extracted_files": extracted_files,
        },
        "parameters": {"recent_days": recent_days},
        "summary": {
            "unknown_extracted_artifact_ids": len(sec_unknown),
            "ambiguous_commit_links": len(sec_ambiguous),
            "recent_unlinked_commits": len(sec_recent),
            "canonical_events_without_commit_refs": len(sec_no_refs),
            "known_artifacts_without_commit_evidence": len(sec_no_evidence),
        },
        "sections": {
            "unknown_extracted_artifact_ids": sec_unknown,
            "ambiguous_commit_links": sec_ambiguous,
            "recent_unlinked_commits": sec_recent,
            "canonical_events_without_commit_refs": sec_no_refs,
            "known_artifacts_without_commit_evidence": sec_no_evidence,
        },
    }


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_health_report_json(report: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return output_path


def _adoc_escape(value: object) -> str:
    return str("" if value is None else value).replace("|", r"\|").replace("\n", " ")


def write_health_report_adoc(report: dict, output_path: Path) -> Path:  # noqa: C901
    lines: list[str] = []
    a = lines.append

    summary = report.get("summary", {})
    sections = report.get("sections", {})
    params = report.get("parameters", {})
    generated_at = report.get("generated_at", "")

    a("= Project Memory Health Report")
    a("")
    a("[NOTE]")
    a("====")
    a("This is a *derived diagnostic report* generated from canonical project_memory and")
    a("extracted Git commit evidence. It is not canonical truth. All findings require")
    a("human review before any canonical data is changed.")
    a("====")
    a("")
    a(f"Generated: `{generated_at}`")
    a(f"Lookback window: `{params.get('recent_days', 14)}` days (recent-unlinked check).")
    a("")

    a("== Summary")
    a("")
    a('[cols="4,1", options="header"]')
    a("|===")
    a("| Check | Count")
    for key, label in [
        ("unknown_extracted_artifact_ids", "Unknown extracted artifact IDs"),
        ("ambiguous_commit_links", "Ambiguous commit links"),
        ("recent_unlinked_commits", "Recent unlinked commits"),
        ("canonical_events_without_commit_refs", "Activity events without commit_refs"),
        ("known_artifacts_without_commit_evidence", "FTRs/BUGs without commit evidence"),
    ]:
        a(f"| {label} | {summary.get(key, 0)}")
    a("|===")
    a("")

    # --- Check 1 ---
    a("== Unknown Extracted Artifact IDs")
    a("")
    rows = sections.get("unknown_extracted_artifact_ids", [])
    if not rows:
        a("_No unknown artifact IDs detected._")
    else:
        a("Artifact IDs found in commit evidence that are absent from canonical memory.")
        a("May indicate old IDs, typos, or aliases that need canonicalization.")
        a("")
        a('[cols="4,1,3", options="header"]')
        a("|===")
        a("| Artifact ID | Commits | Sample commits")
        for row in rows:
            commits = ", ".join(row.get("sample_commits", []))
            a(f"| `{row['artifact_id']}` | {row['commit_count']} | {commits}")
        a("|===")
    a("")

    # --- Check 2 ---
    a("== Ambiguous Commit Links")
    a("")
    rows = sections.get("ambiguous_commit_links", [])
    if not rows:
        a("_No ambiguous commit links._")
    else:
        a("Commits that reference multiple artifact IDs (`match_source: multiple`).")
        a("Human review needed to confirm which association is primary.")
        a("")
        a('[cols="2,1,3,4", options="header"]')
        a("|===")
        a("| Commit | Date | Artifact IDs | Subject")
        for row in rows:
            ids = ", ".join(f"`{i}`" for i in row.get("artifact_ids", []))
            subject = _adoc_escape(row.get("subject", ""))
            a(f"| `{row['short_hash']}` | {row['commit_date']} | {ids} | {subject}")
        a("|===")
    a("")

    # --- Check 3 ---
    recent_days = params.get("recent_days", 14)
    a(f"== Recent Unlinked Commits (last {recent_days} days)")
    a("")
    rows = sections.get("recent_unlinked_commits", [])
    if not rows:
        a("_No recent commits without artifact links._")
    else:
        a("Recent commits with no artifact ID in scope, subject, or body.")
        a("")
        a('[cols="2,1,1,4", options="header"]')
        a("|===")
        a("| Commit | Date | Type | Subject")
        for row in rows:
            subject = _adoc_escape(row.get("subject", ""))
            a(f"| `{row['short_hash']}` | {row['commit_date']} | {row.get('type', '')} | {subject}")
        a("|===")
    a("")

    # --- Check 4 ---
    a("== Activity Events Without Commit References")
    a("")
    rows = sections.get("canonical_events_without_commit_refs", [])
    if not rows:
        a("_All canonical activity events have commit_refs populated._")
        a("")
        a("[NOTE]")
        a("====")
        a("Only `source_type == activity` events (or `SIG-ACT-*` IDs) are checked.")
        a("Non-activity event types (review_set, finding, release, manual_note) are")
        a("structurally expected to omit commit_refs and are excluded.")
        a("====")
    else:
        a("Activity events in `concern_events.json` with no `commit_refs` populated.")
        a("")
        a('[cols="3,1,2,4", options="header"]')
        a("|===")
        a("| ID | Date | Source type | Summary")
        for row in rows:
            summary_text = _adoc_escape(row.get("summary", ""))
            a(f"| `{row['id']}` | {row['event_date']} | {row['source_type']} | {summary_text}")
        a("|===")
    a("")

    # --- Check 5 ---
    a("== FTRs/BUGs Without Commit Evidence")
    a("")
    rows = sections.get("known_artifacts_without_commit_evidence", [])
    if not rows:
        a("_All canonical FTRs/BUGs have at least one linked commit._")
    else:
        a(f"_{len(rows)} canonical FTR/BUG artifact(s) have no direct commit evidence in `commit_signals.json`._")
        a("")
        a("[NOTE]")
        a("====")
        a("Informational only. Artifacts may legitimately lack direct commit evidence")
        a("(pre-history, external work, or conceptual entries). Commit evidence is")
        a("heuristic evidence, not a completeness requirement.")
        a("====")
        a("")
        a('[cols="5,2,1", options="header"]')
        a("|===")
        a("| Artifact ID | Status | Priority")
        for row in rows:
            a(f"| `{row['id']}` | {row.get('status', '')} | {row.get('priority', '')}")
        a("|===")
    a("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return output_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate_and_write(
    canonical_dir: Path = CANONICAL_DIR,
    extracted_dir: Path = EXTRACTED_DIR,
    derived_dir: Path = DERIVED_DIR,
    recent_days: int = 14,
) -> tuple[Path, Path]:
    report = build_health_report(canonical_dir, extracted_dir, recent_days)
    json_path = write_health_report_json(report, derived_dir / "memory_health_report.json")
    adoc_path = write_health_report_adoc(report, derived_dir / "memory_health_report.adoc")
    summary = report["summary"]
    print(
        f"Health report: unknown_ids={summary['unknown_extracted_artifact_ids']}"
        f" ambiguous={summary['ambiguous_commit_links']}"
        f" recent_unlinked={summary['recent_unlinked_commits']}"
        f" events_no_refs={summary['canonical_events_without_commit_refs']}"
        f" no_evidence={summary['known_artifacts_without_commit_evidence']}"
    )
    return json_path, adoc_path


if __name__ == "__main__":
    json_out, adoc_out = generate_and_write()
    print(json_out)
    print(adoc_out)
