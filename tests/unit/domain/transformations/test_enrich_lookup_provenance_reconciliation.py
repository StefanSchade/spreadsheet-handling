"""Lookup-owned reconciliation of ``enrich_lookup`` provenance after removal.

Characterizes ``reconcile_enrich_lookup_provenance`` (H5 in the FK/Lookup
Cycle-0 assessment) in isolation: the predicate depends only on Lookup's own
declared ``helper_columns`` and post-mutation frame state, never on an FK
relation object or FK policy.
"""
from __future__ import annotations

import pytest

from spreadsheet_handling.domain.transformations.enrich_lookup import (
    reconcile_enrich_lookup_provenance,
)

pytestmark = pytest.mark.ftr("FTR-DERIVED-PROVENANCE-NESTED-OWNERSHIP-P4A")


def test_declared_helper_still_present_is_retained() -> None:
    record = {"lookup": "B", "on": ["id"], "helper_columns": ["title"]}
    assert reconcile_enrich_lookup_provenance(
        record, frame_name="A", present_columns={"title", "unrelated"}
    ) is True


def test_partial_overlap_is_retained() -> None:
    record = {
        "lookup": "B",
        "on": ["id"],
        "helper_columns": ["title", "code"],
    }
    assert reconcile_enrich_lookup_provenance(
        record, frame_name="A", present_columns={"code"}
    ) is True


def test_no_declared_helper_remaining_is_dropped() -> None:
    record = {"lookup": "B", "on": ["id"], "helper_columns": ["title"]}
    assert reconcile_enrich_lookup_provenance(
        record, frame_name="A", present_columns={"unrelated"}
    ) is False


def test_empty_declared_helper_columns_is_dropped() -> None:
    record = {"lookup": "B", "on": ["id"], "helper_columns": []}
    assert reconcile_enrich_lookup_provenance(
        record, frame_name="A", present_columns={"anything"}
    ) is False


def test_missing_helper_columns_key_is_dropped() -> None:
    record = {"lookup": "B", "on": ["id"]}
    assert reconcile_enrich_lookup_provenance(
        record, frame_name="A", present_columns={"anything"}
    ) is False


def test_repeated_reconciliation_is_idempotent() -> None:
    record = {"lookup": "B", "on": ["id"], "helper_columns": ["title"]}
    first = reconcile_enrich_lookup_provenance(
        record, frame_name="A", present_columns={"title"}
    )
    second = reconcile_enrich_lookup_provenance(
        record, frame_name="A", present_columns={"title"}
    )
    assert first == second is True

    after_removal = reconcile_enrich_lookup_provenance(
        record, frame_name="A", present_columns=set()
    )
    repeated = reconcile_enrich_lookup_provenance(
        record, frame_name="A", present_columns=set()
    )
    assert after_removal == repeated is False


def test_non_mapping_record_is_left_to_caller_and_not_raised() -> None:
    assert reconcile_enrich_lookup_provenance(
        None, frame_name="A", present_columns={"title"}
    ) is True
    assert reconcile_enrich_lookup_provenance(
        "not-a-record", frame_name="A", present_columns={"title"}
    ) is True


@pytest.mark.parametrize("malformed", ["title", 3, {"title": "x"}])
def test_malformed_helper_columns_fails_clearly(malformed: object) -> None:
    record = {"lookup": "B", "on": ["id"], "helper_columns": malformed}
    with pytest.raises(ValueError) as excinfo:
        reconcile_enrich_lookup_provenance(
            record, frame_name="A", present_columns={"title"}
        )
    message = str(excinfo.value)
    assert "_meta.derived.sheets['A'].enrich_lookup.helper_columns" in message
    assert "must be a list" in message


def test_malformed_error_identifies_the_relevant_frame_path() -> None:
    record = {"helper_columns": "not-a-list"}
    with pytest.raises(ValueError) as excinfo:
        reconcile_enrich_lookup_provenance(
            record, frame_name="OtherSheet", present_columns=set()
        )
    assert "OtherSheet" in str(excinfo.value)
