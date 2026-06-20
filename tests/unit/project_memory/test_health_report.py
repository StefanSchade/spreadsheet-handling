"""Unit tests for the project_memory health report checks.

All tests use in-memory fixtures; no live repository or canonical files needed.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from project_memory.plugins.health_report import (
    _collect_canonical_ids,
    build_health_report,
    check_ambiguous_commit_links,
    check_canonical_events_without_commit_refs,
    check_known_artifacts_without_commit_evidence,
    check_recent_unlinked_commits,
    check_unknown_extracted_artifact_ids,
    write_health_report_adoc,
    write_health_report_json,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _signal(
    short_hash: str,
    commit_date: str,
    confidence: str = "none",
    artifact_ids: list[str] | None = None,
    match_source: str = "none",
    subject: str = "chore: cleanup",
    cc_type: str = "chore",
    scope: str = "",
) -> dict:
    return {
        "id": f"COMMIT-{short_hash}",
        "short_hash": short_hash,
        "commit_date": commit_date,
        "commit_timestamp": f"{commit_date}T10:00:00+00:00",
        "type": cc_type,
        "scope": scope,
        "subject": subject,
        "artifact_ids": artifact_ids or [],
        "artifact_kinds": [aid.split("-")[0] for aid in (artifact_ids or [])],
        "match_source": match_source,
        "confidence": confidence,
        "notes": "",
    }


def _event(
    event_id: str,
    source_type: str = "activity",
    commit_refs: str = "",
    summary: str = "some activity",
) -> dict:
    return {
        "id": event_id,
        "event_date": "2026-06-01",
        "source_type": source_type,
        "commit_refs": commit_refs,
        "summary": summary,
    }


def _ftr(ftr_id: str, status: str = "new", priority: str = "P3") -> dict:
    return {"id": ftr_id, "status": status, "priority": priority}


# ---------------------------------------------------------------------------
# check_unknown_extracted_artifact_ids
# ---------------------------------------------------------------------------

def test_unknown_id_detected():
    signals = [_signal("abc1234", "2026-06-01", confidence="high",
                       artifact_ids=["FTR-UNKNOWN"], match_source="scope")]
    known = {"FTR-KNOWN", "BUG-OTHER"}
    result = check_unknown_extracted_artifact_ids(signals, known)
    assert len(result) == 1
    assert result[0]["artifact_id"] == "FTR-UNKNOWN"
    assert result[0]["commit_count"] == 1
    assert "abc1234" in result[0]["sample_commits"]


def test_known_id_not_reported():
    signals = [_signal("abc1234", "2026-06-01", confidence="high",
                       artifact_ids=["FTR-KNOWN"], match_source="scope")]
    known = {"FTR-KNOWN"}
    result = check_unknown_extracted_artifact_ids(signals, known)
    assert result == []


def test_unknown_id_aggregates_multiple_commits():
    signals = [
        _signal("aaa1111", "2026-06-01", confidence="high",
                artifact_ids=["FTR-GHOST"], match_source="scope"),
        _signal("bbb2222", "2026-06-02", confidence="high",
                artifact_ids=["FTR-GHOST"], match_source="scope"),
    ]
    result = check_unknown_extracted_artifact_ids(signals, set())
    assert result[0]["commit_count"] == 2
    assert sorted(result[0]["sample_commits"]) == ["aaa1111", "bbb2222"]


def test_unknown_id_empty_signals():
    assert check_unknown_extracted_artifact_ids([], {"FTR-X"}) == []


# ---------------------------------------------------------------------------
# check_ambiguous_commit_links
# ---------------------------------------------------------------------------

def test_ambiguous_commit_detected():
    signals = [
        _signal("abc1234", "2026-06-01", confidence="ambiguous",
                artifact_ids=["FTR-A", "BUG-B"], match_source="multiple"),
    ]
    result = check_ambiguous_commit_links(signals)
    assert len(result) == 1
    assert result[0]["short_hash"] == "abc1234"
    assert "FTR-A" in result[0]["artifact_ids"]


def test_high_confidence_not_ambiguous():
    signals = [_signal("abc1234", "2026-06-01", confidence="high",
                       artifact_ids=["FTR-A"], match_source="scope")]
    assert check_ambiguous_commit_links(signals) == []


def test_none_confidence_not_ambiguous():
    signals = [_signal("abc1234", "2026-06-01", confidence="none")]
    assert check_ambiguous_commit_links(signals) == []


# ---------------------------------------------------------------------------
# check_recent_unlinked_commits
# ---------------------------------------------------------------------------

_REFERENCE_DATE = date(2026, 6, 20)


def test_recent_unlinked_inside_window():
    signals = [_signal("abc1234", "2026-06-15", confidence="none")]
    result = check_recent_unlinked_commits(signals, 14, reference_date=_REFERENCE_DATE)
    assert len(result) == 1
    assert result[0]["short_hash"] == "abc1234"


def test_old_unlinked_outside_window():
    signals = [_signal("abc1234", "2026-05-01", confidence="none")]
    result = check_recent_unlinked_commits(signals, 14, reference_date=_REFERENCE_DATE)
    assert result == []


def test_recent_linked_commit_excluded():
    signals = [_signal("abc1234", "2026-06-19", confidence="high",
                       artifact_ids=["FTR-X"], match_source="scope")]
    result = check_recent_unlinked_commits(signals, 14, reference_date=_REFERENCE_DATE)
    assert result == []


def test_cutoff_boundary_inclusive():
    # Exactly at cutoff (14 days before reference) is included
    cutoff = date(2026, 6, 6)  # 2026-06-20 - 14 days
    signals = [_signal("abc1234", cutoff.isoformat(), confidence="none")]
    result = check_recent_unlinked_commits(signals, 14, reference_date=_REFERENCE_DATE)
    assert len(result) == 1


def test_one_day_before_cutoff_excluded():
    one_before = date(2026, 6, 5)  # 15 days before reference
    signals = [_signal("abc1234", one_before.isoformat(), confidence="none")]
    result = check_recent_unlinked_commits(signals, 14, reference_date=_REFERENCE_DATE)
    assert result == []


# ---------------------------------------------------------------------------
# check_canonical_events_without_commit_refs
# ---------------------------------------------------------------------------

def test_activity_event_without_refs_detected():
    events = [_event("SIG-ACT-001", source_type="activity", commit_refs="")]
    result = check_canonical_events_without_commit_refs(events)
    assert len(result) == 1
    assert result[0]["id"] == "SIG-ACT-001"


def test_sig_act_prefix_without_refs_detected():
    events = [_event("SIG-ACT-XYZ", source_type="other_type", commit_refs="")]
    result = check_canonical_events_without_commit_refs(events)
    assert len(result) == 1


def test_activity_event_with_refs_ok():
    events = [_event("SIG-ACT-001", source_type="activity", commit_refs="abc1234, def5678")]
    result = check_canonical_events_without_commit_refs(events)
    assert result == []


def test_non_activity_event_excluded():
    # review_set, finding, release, manual_note events are excluded
    events = [
        _event("SIG-REVIEW-001", source_type="review_set", commit_refs=""),
        _event("SIG-FIN-001", source_type="finding", commit_refs=""),
        _event("SIG-REL-001", source_type="release", commit_refs=""),
        _event("SIG-NOTE-001", source_type="manual_note", commit_refs=""),
    ]
    result = check_canonical_events_without_commit_refs(events)
    assert result == []


# ---------------------------------------------------------------------------
# check_known_artifacts_without_commit_evidence
# ---------------------------------------------------------------------------

def test_ftr_with_evidence_not_reported():
    ftrs = [_ftr("FTR-WITH-EVIDENCE")]
    signals = [_signal("abc1234", "2026-06-01", confidence="high",
                       artifact_ids=["FTR-WITH-EVIDENCE"], match_source="scope")]
    result = check_known_artifacts_without_commit_evidence(ftrs, signals)
    assert result == []


def test_ftr_without_evidence_reported():
    ftrs = [_ftr("FTR-NO-EVIDENCE")]
    signals = [_signal("abc1234", "2026-06-01", confidence="high",
                       artifact_ids=["FTR-OTHER"], match_source="scope")]
    result = check_known_artifacts_without_commit_evidence(ftrs, signals)
    assert len(result) == 1
    assert result[0]["id"] == "FTR-NO-EVIDENCE"
    assert result[0]["status"] == "new"
    assert result[0]["priority"] == "P3"


def test_empty_signals_all_ftrs_without_evidence():
    ftrs = [_ftr("FTR-A"), _ftr("FTR-B")]
    result = check_known_artifacts_without_commit_evidence(ftrs, [])
    assert {r["id"] for r in result} == {"FTR-A", "FTR-B"}


# ---------------------------------------------------------------------------
# build_health_report (integration of checks, with tmp directories)
# ---------------------------------------------------------------------------

def _write_json_file(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_build_health_report_with_tmp_dirs(tmp_path: Path):
    canonical = tmp_path / "canonical"
    extracted = tmp_path / "extracted"
    canonical.mkdir()
    extracted.mkdir()

    _write_json_file(canonical / "ftrs.json", [
        {"id": "FTR-KNOWN", "status": "new", "priority": "P3"},
        {"id": "FTR-NO-COMMIT", "status": "open", "priority": "P4"},
    ])
    _write_json_file(canonical / "concern_events.json", [
        {"id": "SIG-ACT-001", "event_date": "2026-06-01",
         "source_type": "activity", "commit_refs": "abc1234", "summary": "work done"},
        {"id": "SIG-ACT-002", "event_date": "2026-06-05",
         "source_type": "activity", "commit_refs": "", "summary": "work without ref"},
    ])
    _write_json_file(extracted / "commit_signals.json", [
        _signal("abc1234", "2026-06-10", confidence="high",
                artifact_ids=["FTR-KNOWN"], match_source="scope"),
        _signal("def5678", "2026-06-11", confidence="ambiguous",
                artifact_ids=["FTR-KNOWN", "FTR-GHOST"], match_source="multiple"),
        _signal("ghi9012", "2026-06-18", confidence="none"),
    ])

    report = build_health_report(
        canonical_dir=canonical,
        extracted_dir=extracted,
        recent_days=14,
        reference_date=date(2026, 6, 20),
    )

    assert "generated_at" in report
    assert report["parameters"]["recent_days"] == 14

    s = report["summary"]
    assert s["ambiguous_commit_links"] == 1
    assert s["recent_unlinked_commits"] == 1
    assert s["canonical_events_without_commit_refs"] == 1
    assert s["known_artifacts_without_commit_evidence"] == 1  # FTR-NO-COMMIT

    unknown = report["sections"]["unknown_extracted_artifact_ids"]
    assert any(r["artifact_id"] == "FTR-GHOST" for r in unknown)


def test_build_health_report_missing_extracted_file(tmp_path: Path):
    canonical = tmp_path / "canonical"
    extracted = tmp_path / "extracted"
    canonical.mkdir()
    extracted.mkdir()
    _write_json_file(canonical / "ftrs.json", [{"id": "FTR-X"}])
    # No commit_signals.json written

    report = build_health_report(canonical_dir=canonical, extracted_dir=extracted)
    assert report["summary"]["unknown_extracted_artifact_ids"] == 0
    assert report["inputs"]["extracted_files"] == []


# ---------------------------------------------------------------------------
# Writer smoke tests
# ---------------------------------------------------------------------------

def test_write_health_report_json(tmp_path: Path):
    report = {
        "generated_at": "2026-06-20T00:00:00+00:00",
        "inputs": {"canonical_files": [], "extracted_files": []},
        "parameters": {"recent_days": 14},
        "summary": {
            "unknown_extracted_artifact_ids": 2,
            "ambiguous_commit_links": 0,
            "recent_unlinked_commits": 0,
            "canonical_events_without_commit_refs": 0,
            "known_artifacts_without_commit_evidence": 0,
        },
        "sections": {
            "unknown_extracted_artifact_ids": [
                {"artifact_id": "FTR-OLD", "commit_count": 1, "sample_commits": ["abc1234"]},
            ],
            "ambiguous_commit_links": [],
            "recent_unlinked_commits": [],
            "canonical_events_without_commit_refs": [],
            "known_artifacts_without_commit_evidence": [],
        },
    }
    out = tmp_path / "memory_health_report.json"
    write_health_report_json(report, out)

    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert content.endswith("\n")
    loaded = json.loads(content)
    assert loaded["summary"]["unknown_extracted_artifact_ids"] == 2


def test_write_health_report_adoc(tmp_path: Path):
    report = {
        "generated_at": "2026-06-20T00:00:00+00:00",
        "inputs": {"canonical_files": ["ftrs.json"], "extracted_files": ["commit_signals.json"]},
        "parameters": {"recent_days": 14},
        "summary": {
            "unknown_extracted_artifact_ids": 1,
            "ambiguous_commit_links": 0,
            "recent_unlinked_commits": 3,
            "canonical_events_without_commit_refs": 0,
            "known_artifacts_without_commit_evidence": 5,
        },
        "sections": {
            "unknown_extracted_artifact_ids": [
                {"artifact_id": "FTR-GHOST", "commit_count": 2,
                 "sample_commits": ["aaa1111", "bbb2222"]},
            ],
            "ambiguous_commit_links": [],
            "recent_unlinked_commits": [
                {"id": "COMMIT-abc1234", "short_hash": "abc1234",
                 "commit_date": "2026-06-18", "type": "chore", "scope": "",
                 "subject": "cleanup task"},
            ],
            "canonical_events_without_commit_refs": [],
            "known_artifacts_without_commit_evidence": [
                {"id": "FTR-NO-COMMIT", "status": "open", "priority": "P4"},
            ],
        },
    }
    out = tmp_path / "memory_health_report.adoc"
    write_health_report_adoc(report, out)

    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "= Project Memory Health Report" in text
    assert "derived diagnostic report" in text
    assert "FTR-GHOST" in text
    assert "abc1234" in text
    assert "FTR-NO-COMMIT" in text
    assert "All canonical activity events have commit_refs" in text
    assert text.endswith("\n")


def test_adoc_pipe_in_subject_escaped(tmp_path: Path):
    report = {
        "generated_at": "2026-06-20T00:00:00+00:00",
        "inputs": {"canonical_files": [], "extracted_files": []},
        "parameters": {"recent_days": 14},
        "summary": {k: 0 for k in [
            "unknown_extracted_artifact_ids", "ambiguous_commit_links",
            "recent_unlinked_commits", "canonical_events_without_commit_refs",
            "known_artifacts_without_commit_evidence",
        ]},
        "sections": {
            "unknown_extracted_artifact_ids": [],
            "ambiguous_commit_links": [
                {"id": "COMMIT-abc", "short_hash": "abc", "commit_date": "2026-06-01",
                 "type": "feat", "scope": "", "subject": "handle a|b pipe case",
                 "artifact_ids": ["FTR-A", "BUG-B"]},
            ],
            "recent_unlinked_commits": [],
            "canonical_events_without_commit_refs": [],
            "known_artifacts_without_commit_evidence": [],
        },
    }
    out = tmp_path / "report.adoc"
    write_health_report_adoc(report, out)
    text = out.read_text(encoding="utf-8")
    assert r"a\|b" in text


# ---------------------------------------------------------------------------
# _collect_canonical_ids helper
# ---------------------------------------------------------------------------

def test_collect_canonical_ids(tmp_path: Path):
    (tmp_path / "ftrs.json").write_text(
        json.dumps([{"id": "FTR-A"}, {"id": "FTR-B"}, {"other": "no id"}]),
        encoding="utf-8",
    )
    ids = _collect_canonical_ids(tmp_path, ["ftrs.json"])
    assert ids == {"FTR-A", "FTR-B"}


def test_collect_canonical_ids_missing_file(tmp_path: Path):
    ids = _collect_canonical_ids(tmp_path, ["nonexistent.json"])
    assert ids == set()
