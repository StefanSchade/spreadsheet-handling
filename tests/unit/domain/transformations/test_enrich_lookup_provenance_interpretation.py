"""Lookup-owned interpretation of *written* ``enrich_lookup`` provenance.

F-002 Slice 1 (FK / Reference-Helper Domain-family hardening) relocates
provenance-shape validation and symmetric/asymmetric key-form interpretation
here from ``derived_column_policy.py``'s former ``_validated_enrich_spec`` /
``_validated_mismatch_keys`` / ``_validated_symmetric_on`` /
``_validated_single_key``. These tests characterize the two owner-local
entry points in isolation, pinning the exact ``ValueError`` messages/paths
carried over from the relocated code and the shape-vs-key-form laziness
split ``derived_column_policy.py``'s ``drop`` policy depends on (a malformed
or absent join-key form must not raise via the shape-only reader).
"""
from __future__ import annotations

import pytest

from spreadsheet_handling.domain.transformations.enrich_lookup import (
    InterpretedEnrichLookupProvenance,
    interpret_written_enrich_lookup_provenance,
    validated_enrich_lookup_helper_columns,
)

pytestmark = pytest.mark.ftr("FTR-DERIVED-PROVENANCE-NESTED-OWNERSHIP-P4A")


# ---------------------------------------------------------------------------
# interpret_written_enrich_lookup_provenance -- valid records
# ---------------------------------------------------------------------------


def test_symmetric_record_resolves_shared_key_tuple() -> None:
    record = {"lookup": "customers", "on": ["customer_id"], "helper_columns": ["tier"]}
    interpreted = interpret_written_enrich_lookup_provenance(record, frame_name="orders")

    assert interpreted == InterpretedEnrichLookupProvenance(
        lookup_name="customers",
        payload_keys=("customer_id",),
        lookup_keys=("customer_id",),
        helper_columns=("tier",),
    )


def test_asymmetric_record_resolves_distinct_key_tuples() -> None:
    record = {
        "lookup": "stories",
        "source_key": "story_id",
        "lookup_key": "id",
        "helper_columns": ["title"],
    }
    interpreted = interpret_written_enrich_lookup_provenance(record, frame_name="matrix")

    assert interpreted.lookup_name == "stories"
    assert interpreted.payload_keys == ("story_id",)
    assert interpreted.lookup_keys == ("id",)
    assert interpreted.helper_columns == ("title",)


def test_symmetric_multi_key_on_preserves_order() -> None:
    record = {"lookup": "stories", "on": ["id", "part"], "helper_columns": ["title"]}
    interpreted = interpret_written_enrich_lookup_provenance(record, frame_name="matrix")

    assert interpreted.payload_keys == ("id", "part")
    assert interpreted.lookup_keys == ("id", "part")


# ---------------------------------------------------------------------------
# interpret_written_enrich_lookup_provenance -- malformed shape
# ---------------------------------------------------------------------------


def test_non_mapping_record_raises_clear_error() -> None:
    with pytest.raises(ValueError, match=r"enrich_lookup must be a mapping.*str"):
        interpret_written_enrich_lookup_provenance("not-a-record", frame_name="orders")


def test_malformed_helper_columns_raises_clear_error() -> None:
    record = {"lookup": "customers", "on": ["customer_id"], "helper_columns": "tier"}
    with pytest.raises(ValueError, match=r"enrich_lookup\.helper_columns must be a list"):
        interpret_written_enrich_lookup_provenance(record, frame_name="orders")


# ---------------------------------------------------------------------------
# interpret_written_enrich_lookup_provenance -- malformed/absent key form
# ---------------------------------------------------------------------------


def test_mixed_symmetric_and_asymmetric_form_raises() -> None:
    record = {
        "lookup": "stories",
        "on": ["story_id"],
        "source_key": "story_id",
        "helper_columns": ["title"],
    }
    with pytest.raises(ValueError, match="mixes symmetric `on` with asymmetric"):
        interpret_written_enrich_lookup_provenance(record, frame_name="matrix")


def test_partial_asymmetric_pair_raises() -> None:
    record = {"lookup": "stories", "source_key": "story_id", "helper_columns": ["title"]}
    with pytest.raises(ValueError, match=r"requires both `source_key` and `lookup_key`"):
        interpret_written_enrich_lookup_provenance(record, frame_name="matrix")


def test_absent_join_key_form_raises() -> None:
    record = {"lookup": "stories", "helper_columns": ["title"]}
    with pytest.raises(ValueError, match="has no join-key form"):
        interpret_written_enrich_lookup_provenance(record, frame_name="matrix")


@pytest.mark.parametrize(
    "key_form, match",
    [
        ({"source_key": "   ", "lookup_key": "id"}, r"source_key must be a single non-empty string"),
        ({"source_key": "story_id", "lookup_key": 123}, r"lookup_key must be a single non-empty string"),
        ({"on": []}, r"on must be a non-empty list.*empty list"),
        ({"on": [""]}, r"on\[0\] must be a non-empty string.*blank"),
    ],
)
def test_blank_or_non_string_key_members_raise(key_form, match) -> None:
    record = {"lookup": "stories", "helper_columns": ["title"], **key_form}
    with pytest.raises(ValueError, match=match):
        interpret_written_enrich_lookup_provenance(record, frame_name="matrix")


# ---------------------------------------------------------------------------
# validated_enrich_lookup_helper_columns -- shape-only, key-form-blind
# ---------------------------------------------------------------------------


def test_absent_record_is_a_safe_noop() -> None:
    assert validated_enrich_lookup_helper_columns(None, frame_name="orders") == ()


def test_helper_columns_extracted_without_key_form() -> None:
    record = {"lookup": "customers", "on": ["customer_id"], "helper_columns": ["tier", "name"]}
    assert validated_enrich_lookup_helper_columns(record, frame_name="orders") == ("tier", "name")


@pytest.mark.parametrize("key_form", [{}, {"on": None}, {"source_key": None}])
def test_malformed_or_absent_key_form_does_not_raise(key_form) -> None:
    # The shape-only reader must stay value-blind: `derived_column_policy.py`
    # calls it unconditionally (every policy, including `drop`), and a
    # malformed/absent join-key form must not surface here -- only a
    # value-checking policy's later call to
    # `interpret_written_enrich_lookup_provenance` may raise for it.
    record = {"lookup": "stories", "helper_columns": ["title"], **key_form}
    assert validated_enrich_lookup_helper_columns(record, frame_name="matrix") == ("title",)


def test_non_mapping_record_raises_clear_error_for_shape_only_reader() -> None:
    with pytest.raises(ValueError, match=r"enrich_lookup must be a mapping.*int"):
        validated_enrich_lookup_helper_columns(3, frame_name="orders")


def test_malformed_helper_columns_raises_for_shape_only_reader() -> None:
    record = {"lookup": "customers", "helper_columns": {"tier": 1}}
    with pytest.raises(ValueError, match=r"enrich_lookup\.helper_columns must be a list"):
        validated_enrich_lookup_helper_columns(record, frame_name="orders")
