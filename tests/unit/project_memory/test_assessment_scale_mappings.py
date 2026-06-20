"""Unit tests for assessment_scale mapping lookup and validation.

Guards the canonical assessment_scale_mappings.json structure and the
lookup/validation helpers in project_memory.plugins.assessment_scale.
All tests use in-memory fixtures; the live canonical file is only read
in the file-level validation test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_memory.plugins.assessment_scale import (
    build_lookup_index,
    lookup,
    validate_mappings,
)
from project_memory.plugins.queries import finding_assessment_heatmap

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CANONICAL_FILE = (
    Path(__file__).resolve().parents[3]
    / "project_memory" / "canonical" / "assessment_scale_mappings.json"
)


def _entry(
    *,
    id: str = "ASM-TEST-X",
    source_system: str = "finding",
    source_field: str = "severity",
    source_value: str = "critical",
    normalized_scale: str = "impact_0_5",
    normalized_value: int = 5,
    normalized_label: str = "critical",
    notes: str = "",
) -> dict:
    return {
        "id": id,
        "source_system": source_system,
        "source_field": source_field,
        "source_value": source_value,
        "normalized_scale": normalized_scale,
        "normalized_value": normalized_value,
        "normalized_label": normalized_label,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# validate_mappings — structural rules
# ---------------------------------------------------------------------------

def test_valid_mappings_produce_no_errors():
    mappings = [
        _entry(id="ASM-A", source_value="critical", normalized_value=5),
        _entry(id="ASM-B", source_value="low", normalized_value=2),
    ]
    assert validate_mappings(mappings) == []


def test_duplicate_id_is_rejected():
    mappings = [
        _entry(id="ASM-DUP", source_value="critical", normalized_value=5),
        _entry(id="ASM-DUP", source_value="low", normalized_value=2),
    ]
    errors = validate_mappings(mappings)
    assert any("Duplicate id" in e for e in errors)


def test_duplicate_composite_key_is_rejected():
    mappings = [
        _entry(id="ASM-A", source_value="critical", normalized_value=5),
        _entry(id="ASM-B", source_value="critical", normalized_value=5),
    ]
    errors = validate_mappings(mappings)
    assert any("Duplicate mapping key" in e for e in errors)


def test_normalized_value_below_range_is_rejected():
    mappings = [_entry(id="ASM-A", normalized_value=-1)]
    errors = validate_mappings(mappings)
    assert any("outside the allowed range" in e for e in errors)


def test_normalized_value_above_range_is_rejected():
    mappings = [_entry(id="ASM-A", normalized_value=6)]
    errors = validate_mappings(mappings)
    assert any("outside the allowed range" in e for e in errors)


def test_normalized_value_not_integer_is_rejected():
    entry = _entry(id="ASM-A")
    entry["normalized_value"] = 3.5
    errors = validate_mappings([entry])
    assert any("must be an integer" in e for e in errors)


def test_missing_normalized_value_is_rejected():
    entry = _entry(id="ASM-A")
    del entry["normalized_value"]
    errors = validate_mappings([entry])
    assert any("missing 'normalized_value'" in e for e in errors)


def test_boundary_values_0_and_5_are_valid():
    mappings = [
        _entry(id="ASM-ZERO", source_value="none", normalized_value=0),
        _entry(id="ASM-FIVE", source_value="critical", normalized_value=5),
    ]
    assert validate_mappings(mappings) == []


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------

def test_lookup_known_value_returns_entry():
    mappings = [_entry(id="ASM-A", source_value="critical", normalized_value=5)]
    result = lookup(mappings, "finding", "severity", "critical")
    assert result is not None
    assert result["normalized_value"] == 5
    assert result["normalized_label"] == "critical"


def test_lookup_unknown_value_returns_none():
    mappings = [_entry(id="ASM-A", source_value="critical", normalized_value=5)]
    result = lookup(mappings, "finding", "severity", "unknown_label")
    assert result is None


def test_lookup_wrong_source_system_returns_none():
    mappings = [_entry(id="ASM-A", source_system="finding", source_value="critical", normalized_value=5)]
    result = lookup(mappings, "review", "severity", "critical")
    assert result is None


def test_lookup_wrong_source_field_returns_none():
    mappings = [_entry(id="ASM-A", source_field="severity", source_value="critical", normalized_value=5)]
    result = lookup(mappings, "finding", "priority", "critical")
    assert result is None


def test_lookup_respects_normalized_scale():
    mappings = [_entry(id="ASM-A", normalized_scale="impact_0_5", source_value="critical", normalized_value=5)]
    assert lookup(mappings, "finding", "severity", "critical", normalized_scale="impact_0_5") is not None
    assert lookup(mappings, "finding", "severity", "critical", normalized_scale="other_scale") is None


def test_lookup_empty_mappings_returns_none():
    assert lookup([], "finding", "severity", "critical") is None


# ---------------------------------------------------------------------------
# finding_assessment_heatmap query
# ---------------------------------------------------------------------------

import pandas as pd


def _findings_frame(*rows: dict) -> pd.DataFrame:
    columns = ["id", "severity", "topic", "status", "current_relevance"]
    data = [
        {
            "id": r.get("id", "FIN-1"),
            "severity": r.get("severity", "medium"),
            "topic": r.get("topic", "test"),
            "status": r.get("status", "open"),
            "current_relevance": r.get("current_relevance", "current"),
        }
        for r in rows
    ]
    return pd.DataFrame(data, columns=columns) if data else pd.DataFrame(columns=columns)


def _mappings_frame(*entries: dict) -> pd.DataFrame:
    return pd.DataFrame(list(entries)) if entries else pd.DataFrame()


def test_heatmap_maps_known_severity():
    findings = _findings_frame({"id": "FIN-1", "severity": "critical"})
    mappings = _mappings_frame(
        _entry(id="ASM-A", source_system="finding", source_field="severity", source_value="critical", normalized_value=5)
    )
    frames = {"findings": findings, "assessment_scale_mappings": mappings}
    result = finding_assessment_heatmap(frames)
    heatmap = result["finding_assessment_heatmap"]
    assert len(heatmap) == 1
    row = heatmap.iloc[0]
    assert row["id"] == "FIN-1"
    assert int(row["normalized_value"]) == 5
    assert row["normalized_label"] == "critical"
    assert row["mapping_status"] == "mapped"


def test_heatmap_unmapped_severity_reported():
    findings = _findings_frame({"id": "FIN-2", "severity": "unknown_label"})
    mappings = _mappings_frame(
        _entry(id="ASM-A", source_value="critical", normalized_value=5)
    )
    frames = {"findings": findings, "assessment_scale_mappings": mappings}
    result = finding_assessment_heatmap(frames)
    heatmap = result["finding_assessment_heatmap"]
    assert len(heatmap) == 1
    row = heatmap.iloc[0]
    assert row["mapping_status"] == "unmapped"
    assert row["normalized_value"] == ""


def test_heatmap_mixed_mapped_and_unmapped():
    findings = _findings_frame(
        {"id": "FIN-1", "severity": "critical"},
        {"id": "FIN-2", "severity": "ghost_label"},
    )
    mappings = _mappings_frame(
        _entry(id="ASM-A", source_value="critical", normalized_value=5)
    )
    frames = {"findings": findings, "assessment_scale_mappings": mappings}
    result = finding_assessment_heatmap(frames)
    heatmap = result["finding_assessment_heatmap"]
    assert len(heatmap) == 2
    statuses = set(heatmap["mapping_status"].tolist())
    assert statuses == {"mapped", "unmapped"}


def test_heatmap_empty_findings_returns_empty_frame():
    frames: dict = {"findings": pd.DataFrame(), "assessment_scale_mappings": pd.DataFrame()}
    result = finding_assessment_heatmap(frames)
    heatmap = result["finding_assessment_heatmap"]
    assert heatmap.empty


def test_heatmap_missing_mappings_frame_all_unmapped():
    findings = _findings_frame({"id": "FIN-1", "severity": "critical"})
    frames = {"findings": findings}
    result = finding_assessment_heatmap(frames)
    heatmap = result["finding_assessment_heatmap"]
    assert len(heatmap) == 1
    assert heatmap.iloc[0]["mapping_status"] == "unmapped"


def test_heatmap_sorted_high_to_low():
    findings = _findings_frame(
        {"id": "FIN-LOW", "severity": "low"},
        {"id": "FIN-CRIT", "severity": "critical"},
        {"id": "FIN-MED", "severity": "medium"},
    )
    mappings = _mappings_frame(
        _entry(id="ASM-CRIT", source_value="critical", normalized_value=5),
        _entry(id="ASM-MED", source_value="medium", normalized_value=3),
        _entry(id="ASM-LOW", source_value="low", normalized_value=2),
    )
    frames = {"findings": findings, "assessment_scale_mappings": mappings}
    result = finding_assessment_heatmap(frames)
    heatmap = result["finding_assessment_heatmap"]
    values = pd.to_numeric(heatmap["normalized_value"], errors="coerce").tolist()
    assert values == sorted(values, reverse=True)


# ---------------------------------------------------------------------------
# Canonical file self-validation
# ---------------------------------------------------------------------------

def test_canonical_assessment_scale_mappings_file_is_valid():
    assert _CANONICAL_FILE.exists(), f"Canonical mapping file not found: {_CANONICAL_FILE}"
    mappings = json.loads(_CANONICAL_FILE.read_text(encoding="utf-8"))
    assert isinstance(mappings, list), "Canonical file must be a JSON array."
    errors = validate_mappings(mappings)
    assert errors == [], f"Canonical mapping file has validation errors:\n" + "\n".join(errors)


def test_canonical_file_covers_known_finding_severities():
    """Every severity value actually observed in findings.json must have a mapping."""
    observed = {"critical", "major", "medium", "should_fix", "low", "minor", "nice_to_have", "none"}
    mappings = json.loads(_CANONICAL_FILE.read_text(encoding="utf-8"))
    mapped_values = {
        e["source_value"]
        for e in mappings
        if e.get("source_system") == "finding" and e.get("source_field") == "severity"
    }
    missing = observed - mapped_values
    assert not missing, f"Severities present in findings.json but missing from mapping: {sorted(missing)}"
