"""Pathological-cell contracts over the full canonical -> workbook -> canonical cycle.

Assert defined behavior when a cell carries non-domain content: empty FK
source values today, eventually spreadsheet error tokens (``#NAME?``,
``#N/A``, ``#REF!``), NaN-valued numeric cells, etc.

Open issue: see `BUG-UNRESOLVED-HELPER-VALUE-NAN-SEMANTICS-P4A`.
"""

from __future__ import annotations

import pytest


pytestmark = [
    pytest.mark.roundtrip,
    pytest.mark.ftr("FTR-ROUNDTRIP-TEST-LAYER-P4A"),
]


@pytest.mark.xfail(
    reason="BUG-UNRESOLVED-HELPER-VALUE-NAN-SEMANTICS-P4A: the framework "
    "currently has no defined contract for unresolved helper values. The "
    "candidate contract asserted here (\"helper column is absent OR its "
    "value is null\") may be tightened or relaxed once the contract "
    "decision lands.",
    strict=False,
)
def test_empty_fk_source_helper_representation(minimal_fk_workdir) -> None:
    """Unresolved helper values must have a defined canonical representation.

    The fixture row ``ITEM-003`` has ``entity_id: ""``. After the round
    trip, the FK helper ``_entities_name`` either must be absent from
    the row (cleanup honored) or must carry a representation
    distinguishable from ordinary domain data. The literal string
    ``"nan"`` -- a pandas/numpy stringification artifact observed in
    the worldbuilding adoption -- is explicitly *not* a defined
    contract value.

    The assertion below names a candidate post-decision contract:
    "the helper column is absent OR its value is ``None``". When
    ``BUG-UNRESOLVED-HELPER-VALUE-NAN-SEMANTICS-P4A`` decides the
    representation (empty string, structured finding, typed error
    token, or other), this test transitions to green and the
    assertion may need to be tightened to the chosen shape.
    """
    assert minimal_fk_workdir.run_forward() == 0
    assert minimal_fk_workdir.run_reverse() == 0

    items = minimal_fk_workdir.load_reimport("items")
    unresolved = next(
        (row for row in items if row.get("entity_id") in ("", None)),
        None,
    )
    assert unresolved is not None, (
        "fixture invariant: items.json must contain a row with empty "
        "entity_id (ITEM-003); the unresolved-helper contract test "
        "depends on this seed shape."
    )

    helper_column = "_entities_name"
    helper_absent = helper_column not in unresolved
    helper_value = unresolved.get(helper_column)
    helper_is_null = helper_value is None

    # Defense against the specific observed regression: the literal
    # string "nan" is never a valid representation, whatever contract
    # is eventually chosen.
    assert helper_value != "nan", (
        f"unresolved helper value must not be the literal string 'nan' "
        f"(pandas/numpy stringification artifact); row was {unresolved!r}"
    )

    assert helper_absent or helper_is_null, (
        f"unresolved helper {helper_column!r} must be absent or null; "
        f"got value {helper_value!r} in row {unresolved!r}"
    )
