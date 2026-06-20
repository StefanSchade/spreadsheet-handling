"""Unit tests for the concern heatmap query.

Guards finding→concern aggregation, relevance factors, heat bucketing,
gap reporting, and stable output columns.
All tests use in-memory fixtures; no live repository or canonical data needed.
"""
from __future__ import annotations

import pandas as pd
import pytest

from project_memory.plugins.queries import (
    _ACTIVE_RELEVANCE,
    _CLOSED_RELEVANCE,
    _DEFAULT_RELEVANCE_FACTOR,
    _RELEVANCE_FACTORS,
    _WATCH_RELEVANCE,
    _concern_interpretation,
    _finding_to_concern_map,
    _normalized_impact_value,
    _relevance_factor,
    concern_heatmap,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _findings(*rows: dict) -> pd.DataFrame:
    cols = ["id", "severity", "topic", "status", "current_relevance"]
    data = [
        {
            "id": r.get("id", "FIN-X"),
            "severity": r.get("severity", "medium"),
            "topic": r.get("topic", "misc"),
            "status": r.get("status", "open"),
            "current_relevance": r.get("current_relevance", "current"),
        }
        for r in rows
    ]
    return pd.DataFrame(data, columns=cols) if data else pd.DataFrame(columns=cols)


def _concerns(*rows: dict) -> pd.DataFrame:
    cols = ["id", "title", "status", "posture", "priority"]
    data = [
        {
            "id": r.get("id", "CONC-X"),
            "title": r.get("title", "Test concern"),
            "status": r.get("status", "active"),
            "posture": r.get("posture", "doing_now"),
            "priority": r.get("priority", "high"),
        }
        for r in rows
    ]
    return pd.DataFrame(data, columns=cols) if data else pd.DataFrame(columns=cols)


def _events(*rows: dict) -> pd.DataFrame:
    cols = ["id", "source_type", "source_id"]
    data = [{"id": r["id"], "source_type": r["source_type"], "source_id": r["source_id"]} for r in rows]
    return pd.DataFrame(data, columns=cols) if data else pd.DataFrame(columns=cols)


def _xrefs(*rows: dict) -> pd.DataFrame:
    cols = ["id", "event_id", "concern_id", "event_role", "notes"]
    data = [
        {
            "id": r.get("id", "CTSX-X"),
            "event_id": r["event_id"],
            "concern_id": r["concern_id"],
            "event_role": r.get("event_role", "evidence"),
            "notes": r.get("notes", ""),
        }
        for r in rows
    ]
    return pd.DataFrame(data, columns=cols) if data else pd.DataFrame(columns=cols)


def _mappings(*entries: dict) -> pd.DataFrame:
    return pd.DataFrame(list(entries)) if entries else pd.DataFrame()


def _asm(source_value: str, norm_value: int, source_system: str = "finding") -> dict:
    return {
        "id": f"ASM-{source_system.upper()}-{source_value.upper()}",
        "source_system": source_system,
        "source_field": "severity",
        "source_value": source_value,
        "normalized_scale": "impact_0_5",
        "normalized_value": norm_value,
        "normalized_label": source_value,
        "notes": "",
    }


# ---------------------------------------------------------------------------
# _relevance_factor
# ---------------------------------------------------------------------------

def test_relevance_factor_current():
    assert _relevance_factor("current") == 1.0


def test_relevance_factor_partial():
    assert _relevance_factor("partial") == 0.6


def test_relevance_factor_historical():
    assert _relevance_factor("historical") == 0.2


def test_relevance_factor_unknown_uses_default():
    assert _relevance_factor("something_else") == _DEFAULT_RELEVANCE_FACTOR


def test_relevance_sets_are_disjoint():
    assert _ACTIVE_RELEVANCE.isdisjoint(_WATCH_RELEVANCE)
    assert _ACTIVE_RELEVANCE.isdisjoint(_CLOSED_RELEVANCE)
    assert _WATCH_RELEVANCE.isdisjoint(_CLOSED_RELEVANCE)


# ---------------------------------------------------------------------------
# _concern_interpretation
# ---------------------------------------------------------------------------

def test_interpretation_high():
    assert _concern_interpretation(4.0) == "high aggregate impact"
    assert _concern_interpretation(5.0) == "high aggregate impact"


def test_interpretation_moderate():
    assert _concern_interpretation(2.0) == "moderate aggregate impact"
    assert _concern_interpretation(3.9) == "moderate aggregate impact"


def test_interpretation_low():
    assert _concern_interpretation(0.1) == "low aggregate impact"
    assert _concern_interpretation(1.9) == "low aggregate impact"


def test_interpretation_none():
    assert _concern_interpretation(0.0) == "no linked finding signals"


# ---------------------------------------------------------------------------
# _finding_to_concern_map
# ---------------------------------------------------------------------------

def test_map_links_finding_via_event():
    evts = _events({"id": "SIG-CONC-X", "source_type": "finding", "source_id": "FIN-1"})
    xr = _xrefs({"id": "X1", "event_id": "SIG-CONC-X", "concern_id": "CONC-A"})
    result = _finding_to_concern_map(evts, xr)
    assert result == {"FIN-1": ["CONC-A"]}


def test_map_returns_empty_for_non_finding_events():
    evts = _events({"id": "SIG-ACT-X", "source_type": "activity", "source_id": "FIN-1"})
    xr = _xrefs({"id": "X1", "event_id": "SIG-ACT-X", "concern_id": "CONC-A"})
    result = _finding_to_concern_map(evts, xr)
    assert result == {}


def test_map_returns_empty_for_empty_inputs():
    assert _finding_to_concern_map(pd.DataFrame(), pd.DataFrame()) == {}


def test_map_one_finding_to_multiple_concerns():
    evts = _events({"id": "SIG-1", "source_type": "finding", "source_id": "FIN-1"})
    xr = _xrefs(
        {"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-A"},
        {"id": "X2", "event_id": "SIG-1", "concern_id": "CONC-B"},
    )
    result = _finding_to_concern_map(evts, xr)
    assert sorted(result["FIN-1"]) == ["CONC-A", "CONC-B"]


def test_map_no_duplicate_concern_ids_per_finding():
    evts = _events({"id": "SIG-1", "source_type": "finding", "source_id": "FIN-1"})
    xr = _xrefs(
        {"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-A"},
        {"id": "X2", "event_id": "SIG-1", "concern_id": "CONC-A"},
    )
    result = _finding_to_concern_map(evts, xr)
    assert result["FIN-1"].count("CONC-A") == 1


# ---------------------------------------------------------------------------
# concern_heatmap — basic contract
# ---------------------------------------------------------------------------

def _base_frames(findings=None, concerns=None, events=None, xrefs=None, mappings=None):
    return {
        "findings": findings if findings is not None else pd.DataFrame(),
        "concerns": concerns if concerns is not None else pd.DataFrame(),
        "concern_events": events if events is not None else pd.DataFrame(),
        "concern_event_xrefs": xrefs if xrefs is not None else pd.DataFrame(),
        "assessment_scale_mappings": mappings if mappings is not None else pd.DataFrame(),
    }


def test_empty_concerns_returns_empty_heatmap():
    frames = _base_frames()
    out = concern_heatmap(frames)
    assert out["concern_heatmap"].empty
    assert out["finding_concern_mapping_gaps"].empty


def test_concern_with_no_findings_has_zero_heat():
    c = _concerns({"id": "CONC-A"})
    frames = _base_frames(concerns=c)
    out = concern_heatmap(frames)
    hm = out["concern_heatmap"]
    assert len(hm) == 1
    row = hm.iloc[0]
    assert row["concern_id"] == "CONC-A"
    assert float(row["total_heat"]) == 0.0
    assert row["interpretation_note"] == "no linked finding signals"


def test_mapped_finding_contributes_active_heat():
    f = _findings({"id": "FIN-1", "severity": "medium", "current_relevance": "current"})
    c = _concerns({"id": "CONC-A"})
    evts = _events({"id": "SIG-1", "source_type": "finding", "source_id": "FIN-1"})
    xr = _xrefs({"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-A"})
    maps = _mappings(_asm("medium", 3))
    frames = _base_frames(findings=f, concerns=c, events=evts, xrefs=xr, mappings=maps)
    out = concern_heatmap(frames)
    hm = out["concern_heatmap"]
    row = hm.iloc[0]
    assert float(row["active_heat"]) == pytest.approx(3.0)
    assert float(row["watch_heat"]) == pytest.approx(0.0)
    assert float(row["total_heat"]) == pytest.approx(3.0)
    assert int(row["max_impact"]) == 3
    assert row["interpretation_note"] == "moderate aggregate impact"


def test_partial_relevance_goes_to_watch_heat():
    f = _findings({"id": "FIN-1", "severity": "low", "current_relevance": "partial"})
    c = _concerns({"id": "CONC-A"})
    evts = _events({"id": "SIG-1", "source_type": "finding", "source_id": "FIN-1"})
    xr = _xrefs({"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-A"})
    maps = _mappings(_asm("low", 2))
    frames = _base_frames(findings=f, concerns=c, events=evts, xrefs=xr, mappings=maps)
    out = concern_heatmap(frames)
    row = out["concern_heatmap"].iloc[0]
    assert float(row["active_heat"]) == pytest.approx(0.0)
    assert float(row["watch_heat"]) == pytest.approx(2 * 0.6)
    assert float(row["closed_heat"]) == pytest.approx(0.0)


def test_historical_relevance_goes_to_closed_heat():
    f = _findings({"id": "FIN-1", "severity": "medium", "current_relevance": "historical"})
    c = _concerns({"id": "CONC-A"})
    evts = _events({"id": "SIG-1", "source_type": "finding", "source_id": "FIN-1"})
    xr = _xrefs({"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-A"})
    maps = _mappings(_asm("medium", 3))
    frames = _base_frames(findings=f, concerns=c, events=evts, xrefs=xr, mappings=maps)
    out = concern_heatmap(frames)
    row = out["concern_heatmap"].iloc[0]
    assert float(row["closed_heat"]) == pytest.approx(3 * 0.2)
    assert float(row["active_heat"]) == pytest.approx(0.0)


def test_unmapped_severity_finding_does_not_contribute_heat():
    f = _findings({"id": "FIN-1", "severity": "ghost_label"})
    c = _concerns({"id": "CONC-A"})
    evts = _events({"id": "SIG-1", "source_type": "finding", "source_id": "FIN-1"})
    xr = _xrefs({"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-A"})
    maps = _mappings(_asm("medium", 3))
    frames = _base_frames(findings=f, concerns=c, events=evts, xrefs=xr, mappings=maps)
    out = concern_heatmap(frames)
    row = out["concern_heatmap"].iloc[0]
    assert float(row["total_heat"]) == pytest.approx(0.0)
    assert int(row["finding_count"]) == 1
    assert int(row["unmapped_finding_count"]) == 1


def test_finding_without_concern_link_appears_in_gaps():
    f = _findings({"id": "FIN-ORPHAN", "severity": "medium"})
    c = _concerns({"id": "CONC-A"})
    maps = _mappings(_asm("medium", 3))
    frames = _base_frames(findings=f, concerns=c, mappings=maps)
    out = concern_heatmap(frames)
    gaps = out["finding_concern_mapping_gaps"]
    assert len(gaps) == 1
    assert gaps.iloc[0]["finding_id"] == "FIN-ORPHAN"
    assert gaps.iloc[0]["gap_reason"] == "no_concern_link"


def test_finding_with_unmapped_severity_and_concern_link_appears_in_gaps():
    f = _findings({"id": "FIN-1", "severity": "ghost_label"})
    c = _concerns({"id": "CONC-A"})
    evts = _events({"id": "SIG-1", "source_type": "finding", "source_id": "FIN-1"})
    xr = _xrefs({"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-A"})
    maps = _mappings(_asm("medium", 3))
    frames = _base_frames(findings=f, concerns=c, events=evts, xrefs=xr, mappings=maps)
    out = concern_heatmap(frames)
    gaps = out["finding_concern_mapping_gaps"]
    assert len(gaps) == 1
    assert gaps.iloc[0]["gap_reason"] == "unmapped_severity"


def test_heatmap_sorted_highest_heat_first():
    f = _findings(
        {"id": "FIN-LOW", "severity": "low", "current_relevance": "current"},
        {"id": "FIN-HIGH", "severity": "major", "current_relevance": "current"},
    )
    c = _concerns(
        {"id": "CONC-A"},
        {"id": "CONC-B"},
    )
    evts = _events(
        {"id": "SIG-1", "source_type": "finding", "source_id": "FIN-LOW"},
        {"id": "SIG-2", "source_type": "finding", "source_id": "FIN-HIGH"},
    )
    xr = _xrefs(
        {"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-A"},
        {"id": "X2", "event_id": "SIG-2", "concern_id": "CONC-B"},
    )
    maps = _mappings(_asm("low", 2), _asm("major", 4))
    frames = _base_frames(findings=f, concerns=c, events=evts, xrefs=xr, mappings=maps)
    out = concern_heatmap(frames)
    hm = out["concern_heatmap"]
    heats = pd.to_numeric(hm["total_heat"], errors="coerce").tolist()
    assert heats == sorted(heats, reverse=True)


def test_multiple_findings_aggregated_correctly():
    f = _findings(
        {"id": "FIN-1", "severity": "medium", "current_relevance": "current"},
        {"id": "FIN-2", "severity": "low", "current_relevance": "current"},
    )
    c = _concerns({"id": "CONC-A"})
    evts = _events(
        {"id": "SIG-1", "source_type": "finding", "source_id": "FIN-1"},
        {"id": "SIG-2", "source_type": "finding", "source_id": "FIN-2"},
    )
    xr = _xrefs(
        {"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-A"},
        {"id": "X2", "event_id": "SIG-2", "concern_id": "CONC-A"},
    )
    maps = _mappings(_asm("medium", 3), _asm("low", 2))
    frames = _base_frames(findings=f, concerns=c, events=evts, xrefs=xr, mappings=maps)
    out = concern_heatmap(frames)
    row = out["concern_heatmap"].iloc[0]
    assert int(row["finding_count"]) == 2
    assert int(row["mapped_finding_count"]) == 2
    assert float(row["total_heat"]) == pytest.approx(5.0)  # 3*1.0 + 2*1.0
    assert int(row["max_impact"]) == 3
    assert float(row["avg_impact"]) == pytest.approx(2.5)


def test_output_columns_are_stable():
    frames = _base_frames(concerns=_concerns({"id": "CONC-A"}))
    out = concern_heatmap(frames)
    expected_heatmap = [
        "concern_id", "concern_title", "concern_status", "concern_posture", "concern_priority",
        "finding_count", "mapped_finding_count", "unmapped_finding_count",
        "active_heat", "watch_heat", "closed_heat", "total_heat",
        "max_impact", "avg_impact",
        "top_finding_ids", "top_finding_topics", "interpretation_note",
    ]
    expected_gaps = [
        "finding_id", "severity", "topic", "status", "current_relevance",
        "normalized_value", "gap_reason",
    ]
    assert list(out["concern_heatmap"].columns) == expected_heatmap
    assert list(out["finding_concern_mapping_gaps"].columns) == expected_gaps


def test_no_invented_concern_mapping():
    """A finding linked to a non-existent concern must not appear in the heatmap."""
    f = _findings({"id": "FIN-1", "severity": "medium"})
    c = _concerns({"id": "CONC-A"})
    evts = _events({"id": "SIG-1", "source_type": "finding", "source_id": "FIN-1"})
    xr = _xrefs({"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-PHANTOM"})
    maps = _mappings(_asm("medium", 3))
    frames = _base_frames(findings=f, concerns=c, events=evts, xrefs=xr, mappings=maps)
    out = concern_heatmap(frames)
    hm = out["concern_heatmap"]
    assert len(hm) == 1
    assert hm.iloc[0]["concern_id"] == "CONC-A"
    assert float(hm.iloc[0]["total_heat"]) == 0.0


# ---------------------------------------------------------------------------
# _normalized_impact_value — stringly-typed boundary casting
# ---------------------------------------------------------------------------

def test_normalized_impact_value_int_in_range():
    assert _normalized_impact_value({"normalized_value": 3}) == 3


def test_normalized_impact_value_zero():
    assert _normalized_impact_value({"normalized_value": 0}) == 0


def test_normalized_impact_value_five():
    assert _normalized_impact_value({"normalized_value": 5}) == 5


def test_normalized_impact_value_integer_float():
    assert _normalized_impact_value({"normalized_value": 3.0}) == 3


def test_normalized_impact_value_string_int():
    assert _normalized_impact_value({"normalized_value": "3"}) == 3


def test_normalized_impact_value_string_integer_float():
    assert _normalized_impact_value({"normalized_value": "3.0"}) == 3


def test_normalized_impact_value_none_mapping():
    assert _normalized_impact_value(None) is None


def test_normalized_impact_value_missing_key():
    assert _normalized_impact_value({}) is None


def test_normalized_impact_value_none_value():
    assert _normalized_impact_value({"normalized_value": None}) is None


def test_normalized_impact_value_empty_string():
    assert _normalized_impact_value({"normalized_value": ""}) is None


def test_normalized_impact_value_non_numeric_string():
    assert _normalized_impact_value({"normalized_value": "not-a-number"}) is None


def test_normalized_impact_value_fractional_float():
    assert _normalized_impact_value({"normalized_value": 3.5}) is None


def test_normalized_impact_value_fractional_string():
    assert _normalized_impact_value({"normalized_value": "3.5"}) is None


def test_normalized_impact_value_out_of_range_high():
    assert _normalized_impact_value({"normalized_value": 6}) is None
    assert _normalized_impact_value({"normalized_value": "6"}) is None


def test_normalized_impact_value_out_of_range_low():
    assert _normalized_impact_value({"normalized_value": -1}) is None
    assert _normalized_impact_value({"normalized_value": "-1"}) is None


# ---------------------------------------------------------------------------
# String normalized_value round-trip through concern_heatmap
# ---------------------------------------------------------------------------

def _linked_frames_with_string_impact(norm_value_str: str) -> dict:
    """Build a minimal frames dict with normalized_value as a string in the mapping."""
    f = _findings({"id": "FIN-1", "severity": "medium", "current_relevance": "current"})
    c = _concerns({"id": "CONC-A"})
    evts = _events({"id": "SIG-1", "source_type": "finding", "source_id": "FIN-1"})
    xr = _xrefs({"id": "X1", "event_id": "SIG-1", "concern_id": "CONC-A"})
    entry = _asm("medium", 3)
    entry["normalized_value"] = norm_value_str  # override with string
    maps = _mappings(entry)
    return _base_frames(findings=f, concerns=c, events=evts, xrefs=xr, mappings=maps)


def test_string_normalized_value_3_produces_heat():
    out = concern_heatmap(_linked_frames_with_string_impact("3"))
    row = out["concern_heatmap"].iloc[0]
    assert float(row["total_heat"]) == pytest.approx(3.0)
    assert int(row["mapped_finding_count"]) == 1
    assert out["finding_concern_mapping_gaps"].empty


def test_string_normalized_value_3_0_produces_heat():
    out = concern_heatmap(_linked_frames_with_string_impact("3.0"))
    row = out["concern_heatmap"].iloc[0]
    assert float(row["total_heat"]) == pytest.approx(3.0)


def test_string_normalized_value_non_numeric_treated_as_unmapped():
    out = concern_heatmap(_linked_frames_with_string_impact("not-a-number"))
    row = out["concern_heatmap"].iloc[0]
    assert float(row["total_heat"]) == pytest.approx(0.0)
    assert int(row["unmapped_finding_count"]) == 1
    gaps = out["finding_concern_mapping_gaps"]
    assert len(gaps) == 1
    assert gaps.iloc[0]["gap_reason"] == "unmapped_severity"


def test_string_normalized_value_fractional_treated_as_unmapped():
    out = concern_heatmap(_linked_frames_with_string_impact("3.5"))
    row = out["concern_heatmap"].iloc[0]
    assert float(row["total_heat"]) == pytest.approx(0.0)
    assert int(row["unmapped_finding_count"]) == 1


def test_string_normalized_value_out_of_range_treated_as_unmapped():
    for bad in ("6", "-1"):
        out = concern_heatmap(_linked_frames_with_string_impact(bad))
        row = out["concern_heatmap"].iloc[0]
        assert float(row["total_heat"]) == pytest.approx(0.0), f"failed for {bad!r}"
