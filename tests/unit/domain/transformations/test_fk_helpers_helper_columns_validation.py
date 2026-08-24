"""FK-owned strict validation of transient ``helper_columns`` provenance.

F-002 Slice 1 (FK / Reference-Helper Domain-family hardening, FIND-C1-002)
relocates the fail-clear reader ``validated_helper_columns`` here from
``derived_column_policy.py``'s former ``_validated_fk_helper_names``. It is
a distinct, owner-local sibling of the existing lenient
``derived_helper_columns_by_sheet`` (which silently skips malformed shapes
for its five existing callers, left unchanged by this slice); this reader
instead raises clearly, matching the relocated code's exact message/path.

Per the independent readiness review's F-CORR-1 correction, this function
takes only the already-extracted per-sheet raw ``helper_columns`` value --
never the full ``frames`` mapping -- so it does not itself re-walk or
re-validate the shared ``_meta.derived``/``_meta.derived.sheets[frame]``
container (that generic validation stays in
``derived_column_policy.py``'s ``_safe_sheet_meta``/
``_resolve_derived_identity``).
"""
from __future__ import annotations

import pytest

from spreadsheet_handling.domain.transformations.fk_helpers import (
    validated_helper_columns,
)

pytestmark = pytest.mark.ftr("FTR-DERIVED-PROVENANCE-NESTED-OWNERSHIP-P4A")


def test_absent_helper_columns_is_a_safe_noop() -> None:
    assert validated_helper_columns(None, frame_name="orders") == set()


def test_valid_transient_helper_provenance_returns_declared_names() -> None:
    raw_helper_columns = [
        {"column": "_customer_name", "fk_column": "customer_id", "target": "customers", "value_field": "name"},
        {"column": "_customer_tier", "fk_column": "customer_id", "target": "customers", "value_field": "tier"},
    ]
    assert validated_helper_columns(raw_helper_columns, frame_name="orders") == {
        "_customer_name",
        "_customer_tier",
    }


def test_entries_without_a_column_are_skipped() -> None:
    raw_helper_columns = [{"fk_column": "customer_id"}, {"column": "_customer_name"}]
    assert validated_helper_columns(raw_helper_columns, frame_name="orders") == {"_customer_name"}


def test_malformed_helper_columns_container_raises_clear_error() -> None:
    with pytest.raises(ValueError, match=r"_meta\.derived\.sheets\['orders'\]\.helper_columns must be a list"):
        validated_helper_columns("not-a-list", frame_name="orders")


def test_malformed_helper_columns_entry_raises_clear_error() -> None:
    with pytest.raises(
        ValueError,
        match=r"_meta\.derived\.sheets\['orders'\]\.helper_columns\[0\] must be a mapping",
    ):
        validated_helper_columns(["_customer_name"], frame_name="orders")
