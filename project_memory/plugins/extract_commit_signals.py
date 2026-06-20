"""Extract Git commit signals into project_memory/extracted/commit_signals.json.

Deterministic, conservative extraction only. No semantic interpretation.
Commits are emitted in reverse-chronological order (git default: newest first).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "project_memory" / "extracted"
OUTPUT_FILE = OUTPUT_DIR / "commit_signals.json"

ARTIFACT_ID_RE = re.compile(
    r"\b(?:FTR|BUG|REV|FIN|ADR|DEC|REL|SIG|CONC)-[A-Z0-9][A-Z0-9_-]*\b"
)
CC_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?!?:\s+(?P<description>.+)$"
)


# ---------------------------------------------------------------------------
# Pure parsing functions (no I/O, fully unit-testable)
# ---------------------------------------------------------------------------

def extract_artifact_ids(text: str) -> list[str]:
    """Return sorted, deduplicated artifact IDs found in text."""
    return sorted(set(ARTIFACT_ID_RE.findall(text)))


def extract_artifact_kinds(ids: list[str]) -> list[str]:
    """Return sorted, deduplicated kind prefixes from a list of artifact IDs."""
    return sorted({aid.split("-")[0] for aid in ids})


def parse_conventional_commit(subject: str) -> tuple[str, str, str]:
    """Parse a commit subject into (type, scope, description).

    Returns ('', '', subject) for non-Conventional Commit subjects.
    """
    m = CC_RE.match(subject)
    if not m:
        return "", "", subject
    return (
        m.group("type") or "",
        m.group("scope") or "",
        m.group("description") or subject,
    )


def normalize_date(timestamp: str) -> str:
    """Extract YYYY-MM-DD from an ISO-strict timestamp (2026-06-19T23:40:05+02:00)."""
    return timestamp[:10]


def compute_signals(
    scope_ids: list[str],
    desc_ids: list[str],
    body_ids: list[str],
) -> tuple[str, str]:
    """Return (confidence, match_source) from IDs found in scope, description, body.

    Body IDs are only consulted when scope_ids and desc_ids are both empty.
    """
    subject_ids = sorted(set(scope_ids + desc_ids))

    if len(subject_ids) > 1:
        return "ambiguous", "multiple"
    if len(subject_ids) == 1:
        if desc_ids:
            return "high", "subject"
        return "high", "scope"

    if len(body_ids) > 1:
        return "ambiguous", "multiple"
    if len(body_ids) == 1:
        return "medium", "body"
    return "none", "none"


def build_row(
    commit_hash: str,
    short_hash: str,
    commit_timestamp: str,
    raw_subject: str,
    body: str = "",
) -> dict:
    """Build a single commit signal row from raw git data.

    The body is only scanned for artifact IDs when none are found in the
    scope or subject (per heuristic step 3 in the spec).
    """
    cc_type, cc_scope, description = parse_conventional_commit(raw_subject)
    scope_ids = extract_artifact_ids(cc_scope)
    desc_ids = extract_artifact_ids(description)
    subject_ids = sorted(set(scope_ids + desc_ids))

    body_ids: list[str] = [] if subject_ids else extract_artifact_ids(body)
    all_ids = sorted(set(subject_ids + body_ids))
    confidence, match_source = compute_signals(scope_ids, desc_ids, body_ids)

    return {
        "id": f"COMMIT-{short_hash}",
        "commit_hash": commit_hash,
        "short_hash": short_hash,
        "commit_date": normalize_date(commit_timestamp),
        "commit_timestamp": commit_timestamp,
        "type": cc_type,
        "scope": cc_scope,
        "subject": description,
        "artifact_ids": all_ids,
        "artifact_kinds": extract_artifact_kinds(all_ids),
        "match_source": match_source,
        "confidence": confidence,
        "notes": "",
    }


# ---------------------------------------------------------------------------
# Git I/O layer
# ---------------------------------------------------------------------------

def fetch_all_commits(
    repo_root: Path,
) -> list[tuple[str, str, str, str, str]]:
    """Run git log and return (hash, short_hash, timestamp, subject, body) tuples.

    Output is in reverse-chronological order (newest first, git default).
    Raises RuntimeError if git is unavailable or the repository cannot be read.
    """
    try:
        result = subprocess.run(
            [
                "git", "log",
                "--date=iso-strict",
                "-z",
                "--pretty=format:%H\t%h\t%ad\t%s\t%b",
            ],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=60,
        )
    except FileNotFoundError:
        raise RuntimeError("git executable not found") from None

    if result.returncode != 0:
        raise RuntimeError(f"git log failed: {result.stderr.strip()}")

    records: list[tuple[str, str, str, str, str]] = []
    for record in result.stdout.split("\x00"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\t", 4)
        if len(parts) < 4:
            continue
        commit_hash, short_hash, timestamp, subject = parts[:4]
        body = parts[4].strip() if len(parts) > 4 else ""
        records.append((commit_hash, short_hash, timestamp, subject, body))

    return records


# ---------------------------------------------------------------------------
# Orchestration and writer
# ---------------------------------------------------------------------------

def extract_commit_signals(repo_root: Path | None = None) -> list[dict]:
    """Extract commit signal rows from git history."""
    if repo_root is None:
        repo_root = ROOT
    return [
        build_row(h, sh, ts, subj, body)
        for h, sh, ts, subj, body in fetch_all_commits(repo_root)
    ]


def _write_json(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def extract_and_write(repo_root: Path | None = None) -> Path:
    rows = extract_commit_signals(repo_root)
    _write_json(OUTPUT_FILE, rows)
    print(f"Commit signals: {len(rows)}")
    return OUTPUT_FILE


if __name__ == "__main__":
    extract_and_write()
