from __future__ import annotations

from project_memory.plugins import render_context as rc


def test_status_is_inactive_recognises_compound_lifecycle_words() -> None:
    assert rc._status_is_inactive("done")
    assert rc._status_is_inactive("done (accepted)")
    assert rc._status_is_inactive("superseded (design absorbed)")
    assert rc._status_is_inactive("closed")
    assert rc._status_is_inactive("wontfix")


def test_status_is_inactive_keeps_active_statuses() -> None:
    assert not rc._status_is_inactive("")
    assert not rc._status_is_inactive("new")
    assert not rc._status_is_inactive("open")
    assert not rc._status_is_inactive("implemented")
    assert not rc._status_is_inactive("new (active)")
    # "resolution" must not be mistaken for the whole word "resolved".
    assert not rc._status_is_inactive("narrow slice (intent-vs-resolution)")


def test_active_ftrs_excludes_done_accepted_and_historical() -> None:
    ftrs = [
        {"id": "FTR-A", "status": "open", "priority": "high", "current_relevance": ""},
        {"id": "FTR-B", "status": "done (accepted)", "priority": "high", "current_relevance": "current"},
        {"id": "FTR-C", "status": "superseded", "priority": "low", "current_relevance": ""},
        {"id": "FTR-D", "status": "new", "priority": "medium", "current_relevance": "historical"},
        {"id": "FTR-E", "status": "implemented", "priority": "medium", "current_relevance": ""},
    ]
    ids = [row["id"] for row in rc._active_ftrs(ftrs)]
    assert ids == ["FTR-A", "FTR-E"]


def test_review_sets_split_current_from_historical() -> None:
    review_sets = [{"id": "REVSET-X", "category": "topic"}]
    reviews = [
        {"id": "REV-1", "review_set_id": "REVSET-X", "date": "2026-01-01", "current_relevance": "historic"},
        {"id": "REV-2", "review_set_id": "REVSET-X", "date": "2026-02-01", "current_relevance": "current"},
        {"id": "REV-3", "review_set_id": "REVSET-X", "date": "2026-03-01", "current_relevance": "partial"},
    ]
    grouped = rc._review_sets_grouped(review_sets, reviews)
    assert len(grouped) == 1
    rendered_ids = {r["id"] for r in grouped[0]["reviews"]}
    assert rendered_ids == {"REV-2", "REV-3"}
    assert grouped[0]["historical_review_count"] == 1


def test_concern_events_capped_to_recent_window() -> None:
    concerns = [{"id": "CONC-X", "status": "active", "posture": "", "priority": "high"}]
    events = [
        {"id": f"SIG-{i:02d}", "event_date": f"2026-01-{i:02d}", "weight": "high", "summary": "x", "notes": ""}
        for i in range(1, rc._MAX_CONCERN_EVENTS + 4)
    ]
    xrefs = [
        {"id": f"X-{e['id']}", "event_id": e["id"], "concern_id": "CONC-X", "event_role": "evidence", "notes": ""}
        for e in events
    ]
    enriched = rc._concerns_with_events(concerns, events, xrefs)
    row = enriched[0]
    assert len(row["events"]) == rc._MAX_CONCERN_EVENTS
    assert row["older_event_count"] == 3
    # Most recent event is kept.
    assert row["events"][0]["event_id"] == f"SIG-{rc._MAX_CONCERN_EVENTS + 3:02d}"


def test_build_render_context_exposes_decisions_and_link_count() -> None:
    context = rc.build_render_context()
    assert "decisions" in context
    assert isinstance(context["event_ftr_link_count"], int)
    # done/superseded FTRs must not appear as active work.
    active_ids = {row["id"] for row in context["active_ftrs"]}
    assert "FTR-XREF-AXIS-MAPPINGS-P4A2" not in active_ids
    assert "FTR-XREF-GROUPED-COLUMNS-P4A2" not in active_ids
