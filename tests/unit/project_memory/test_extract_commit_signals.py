"""Unit tests for extract_commit_signals parsing layer.

All tests operate on pure functions and do not require a live Git repository.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_memory.plugins.extract_commit_signals import (
    _write_json,
    build_row,
    compute_signals,
    extract_artifact_ids,
    extract_artifact_kinds,
    normalize_date,
    parse_conventional_commit,
)


# ---------------------------------------------------------------------------
# parse_conventional_commit
# ---------------------------------------------------------------------------

def test_cc_without_scope():
    t, s, d = parse_conventional_commit("docs: update guide")
    assert t == "docs"
    assert s == ""
    assert d == "update guide"


def test_cc_with_normal_scope():
    t, s, d = parse_conventional_commit("refactor(domain): extract shared where predicates")
    assert t == "refactor"
    assert s == "domain"
    assert d == "extract shared where predicates"


def test_cc_with_artifact_id_in_scope():
    subject = "fix(BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A): strip helper fields before promotion"
    t, s, d = parse_conventional_commit(subject)
    assert t == "fix"
    assert s == "BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A"
    assert d == "strip helper fields before promotion"


def test_cc_with_artifact_id_in_description():
    subject = "docs(backlog): record FTR-XREF-CROSSTABLE-P5 implementation concept"
    t, s, d = parse_conventional_commit(subject)
    assert t == "docs"
    assert s == "backlog"
    assert d == "record FTR-XREF-CROSSTABLE-P5 implementation concept"


def test_non_conventional_subject():
    subject = "Merge branch 'feature/FTR-LEGEND-BLOCKS-LIFECYCLE-P6'"
    t, s, d = parse_conventional_commit(subject)
    assert t == ""
    assert s == ""
    assert d == subject


# ---------------------------------------------------------------------------
# extract_artifact_ids
# ---------------------------------------------------------------------------

def test_extract_ids_from_scope_text():
    ids = extract_artifact_ids("BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A")
    assert ids == ["BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A"]


def test_extract_ids_from_description_text():
    ids = extract_artifact_ids("record FTR-XREF-CROSSTABLE-P5 implementation concept")
    assert ids == ["FTR-XREF-CROSSTABLE-P5"]


def test_extract_ids_deduplication():
    ids = extract_artifact_ids("FTR-X mentioned again: FTR-X")
    assert ids == ["FTR-X"]


def test_extract_ids_no_partial_false_positive():
    ids = extract_artifact_ids("INFRASTRUCTURE is a common word")
    assert ids == []


def test_extract_ids_no_match_on_lowercase_prefix():
    ids = extract_artifact_ids("ftr-lowercase is not an ID")
    assert ids == []


def test_extract_multiple_ids():
    ids = extract_artifact_ids("see FTR-ALPHA and BUG-BETA for context")
    assert ids == ["BUG-BETA", "FTR-ALPHA"]


def test_extract_ids_all_supported_kinds():
    text = "REV-001 FIN-002 ADR-003 DEC-004 REL-005 SIG-006 CONC-007"
    ids = extract_artifact_ids(text)
    assert ids == ["ADR-003", "CONC-007", "DEC-004", "FIN-002", "REL-005", "REV-001", "SIG-006"]


def test_extract_ids_empty_string():
    assert extract_artifact_ids("") == []


# ---------------------------------------------------------------------------
# extract_artifact_kinds
# ---------------------------------------------------------------------------

def test_extract_kinds_deduplication():
    kinds = extract_artifact_kinds(["FTR-A", "BUG-B", "FTR-C"])
    assert kinds == ["BUG", "FTR"]


def test_extract_kinds_empty():
    assert extract_artifact_kinds([]) == []


# ---------------------------------------------------------------------------
# normalize_date
# ---------------------------------------------------------------------------

def test_normalize_date_with_positive_offset():
    assert normalize_date("2026-06-19T23:40:05+02:00") == "2026-06-19"


def test_normalize_date_utc():
    assert normalize_date("2026-01-01T00:00:00+00:00") == "2026-01-01"


def test_normalize_date_negative_offset():
    assert normalize_date("2025-12-31T23:59:59-05:00") == "2025-12-31"


# ---------------------------------------------------------------------------
# compute_signals
# ---------------------------------------------------------------------------

def test_signals_scope_only():
    confidence, source = compute_signals(["BUG-X"], [], [])
    assert confidence == "high"
    assert source == "scope"


def test_signals_description_only():
    confidence, source = compute_signals([], ["FTR-Y"], [])
    assert confidence == "high"
    assert source == "subject"


def test_signals_same_id_in_scope_and_description():
    confidence, source = compute_signals(["FTR-X"], ["FTR-X"], [])
    assert confidence == "high"
    assert source == "subject"


def test_signals_body_only():
    confidence, source = compute_signals([], [], ["FTR-Z"])
    assert confidence == "medium"
    assert source == "body"


def test_signals_ambiguous_multiple_in_subject():
    confidence, source = compute_signals(["FTR-A"], ["BUG-B"], [])
    assert confidence == "ambiguous"
    assert source == "multiple"


def test_signals_ambiguous_multiple_in_body():
    confidence, source = compute_signals([], [], ["FTR-A", "BUG-B"])
    assert confidence == "ambiguous"
    assert source == "multiple"


def test_signals_none():
    confidence, source = compute_signals([], [], [])
    assert confidence == "none"
    assert source == "none"


# ---------------------------------------------------------------------------
# build_row (integration of parsing functions)
# ---------------------------------------------------------------------------

_FAKE_HASH = "abc123def456abc123def456abc123def456abc123"
_FAKE_SHORT = "abc123d"
_FAKE_TS = "2026-06-15T15:26:21+02:00"


def test_build_row_scope_id():
    row = build_row(
        _FAKE_HASH, _FAKE_SHORT, _FAKE_TS,
        "fix(BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A): strip helper fields before promotion",
    )
    assert row["id"] == f"COMMIT-{_FAKE_SHORT}"
    assert row["commit_hash"] == _FAKE_HASH
    assert row["short_hash"] == _FAKE_SHORT
    assert row["commit_date"] == "2026-06-15"
    assert row["commit_timestamp"] == _FAKE_TS
    assert row["type"] == "fix"
    assert row["scope"] == "BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A"
    assert row["subject"] == "strip helper fields before promotion"
    assert row["artifact_ids"] == ["BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A"]
    assert row["artifact_kinds"] == ["BUG"]
    assert row["match_source"] == "scope"
    assert row["confidence"] == "high"
    assert row["notes"] == ""


def test_build_row_subject_id():
    row = build_row(
        "deadbeef1234deadbeef1234deadbeef1234dead", "deadbee",
        "2026-06-14T10:00:00+02:00",
        "docs(backlog): record FTR-XREF-CROSSTABLE-P5 implementation concept",
    )
    assert row["artifact_ids"] == ["FTR-XREF-CROSSTABLE-P5"]
    assert row["artifact_kinds"] == ["FTR"]
    assert row["match_source"] == "subject"
    assert row["confidence"] == "high"


def test_build_row_no_id():
    row = build_row(
        "0000000100000001000000010000000100000001", "0000001",
        "2026-06-19T12:00:00+00:00",
        "chore: update dependencies",
    )
    assert row["artifact_ids"] == []
    assert row["artifact_kinds"] == []
    assert row["match_source"] == "none"
    assert row["confidence"] == "none"


def test_build_row_body_id_only():
    row = build_row(
        "1111111111111111111111111111111111111111", "1111111",
        "2026-06-18T08:00:00+00:00",
        "chore: general maintenance",
        body="This commit relates to FTR-SPECIAL-CASE for context.",
    )
    assert row["artifact_ids"] == ["FTR-SPECIAL-CASE"]
    assert row["match_source"] == "body"
    assert row["confidence"] == "medium"


def test_build_row_body_not_scanned_when_subject_has_id():
    row = build_row(
        "2222222222222222222222222222222222222222", "2222222",
        "2026-06-17T08:00:00+00:00",
        "feat(FTR-ALPHA): implement feature",
        body="Also relates to BUG-BODY-ONLY.",
    )
    assert row["artifact_ids"] == ["FTR-ALPHA"]
    assert row["match_source"] == "scope"
    assert row["confidence"] == "high"


def test_build_row_multiple_ids():
    row = build_row(
        "3333333333333333333333333333333333333333", "3333333",
        "2026-06-16T08:00:00+00:00",
        "feat: implement FTR-ALPHA and close BUG-BETA",
    )
    assert sorted(row["artifact_ids"]) == ["BUG-BETA", "FTR-ALPHA"]
    assert row["match_source"] == "multiple"
    assert row["confidence"] == "ambiguous"


def test_build_row_non_conventional_subject():
    row = build_row(
        "4444444444444444444444444444444444444444", "4444444",
        "2026-06-15T08:00:00+00:00",
        "Merge branch 'feature/develop'",
    )
    assert row["type"] == ""
    assert row["scope"] == ""
    assert row["subject"] == "Merge branch 'feature/develop'"
    assert row["artifact_ids"] == []


# ---------------------------------------------------------------------------
# _write_json smoke test
# ---------------------------------------------------------------------------

def test_write_json_creates_file_with_trailing_newline(tmp_path: Path):
    out = tmp_path / "signals.json"
    rows = [{"id": "COMMIT-abc1234", "notes": ""}]
    _write_json(out, rows)

    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert content.endswith("\n")
    data = json.loads(content)
    assert isinstance(data, list)
    assert data[0]["id"] == "COMMIT-abc1234"


def test_write_json_is_utf8(tmp_path: Path):
    out = tmp_path / "signals.json"
    rows = [{"id": "COMMIT-abc1234", "subject": "feat: add döküman support"}]
    _write_json(out, rows)
    content = out.read_bytes()
    decoded = content.decode("utf-8")
    assert "döküman" in decoded
