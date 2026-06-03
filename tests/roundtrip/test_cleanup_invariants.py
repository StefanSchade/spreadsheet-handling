"""Cleanup invariants over the full canonical -> workbook -> canonical cycle.

Assert that helper-related cleanup intent declared in a reimport pipeline
actually holds at the canonical output, independently of *which step*
implements the invariant. Tests in this file must remain green across
refactors of the production code that provides the invariant.

Open issue: see `BUG-HELPER-CLEANUP-CONTRACT-P4A`.
"""

from __future__ import annotations

import pytest


pytestmark = [
    pytest.mark.roundtrip,
    pytest.mark.ftr("FTR-ROUNDTRIP-TEST-LAYER-P4A"),
]


@pytest.mark.xfail(
    reason="BUG-HELPER-CLEANUP-CONTRACT-P4A: the persistence-boundary fix "
    "removed the _meta.derived channel that apply_derived_column_policy "
    "reads, so the cleanup step is a silent no-op on canonical reimport. "
    "Transitions to green once the cleanup-contract fix lands.",
    strict=True,
)
def test_helper_columns_absent_after_canonical_reimport(minimal_fk_workdir) -> None:
    """Helper columns must not survive into canonical JSON.

    Invariant: a reimport pipeline that declares
    ``apply_derived_column_policy ... policy: drop`` must produce canonical
    JSON in which no helper column appears for the cleaned frame. The
    helper column under test is ``_entities_name`` on the ``items``
    frame; the invariant naturally extends to any future helper column
    on any frame the fixture grows.
    """
    rc_fwd = minimal_fk_workdir.run_forward()
    rc_rev = minimal_fk_workdir.run_reverse()
    assert rc_fwd == 0 and rc_rev == 0, "pipeline runs must complete cleanly"

    items = minimal_fk_workdir.load_reimport("items")
    helper_column = "_entities_name"

    leaking_rows = [
        {"id": row.get("id"), helper_column: row[helper_column]}
        for row in items
        if helper_column in row
    ]
    assert leaking_rows == [], (
        f"helper column {helper_column!r} must be absent from canonical "
        f"items.json after the documented cleanup step; leaking rows: "
        f"{leaking_rows}"
    )
