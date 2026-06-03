"""Pathological-cell contracts over the full canonical -> workbook -> canonical cycle.

Assert defined behavior when a cell carries non-domain content: empty FK
source values today, eventually spreadsheet error tokens (``#NAME?``,
``#N/A``, ``#REF!``), NaN-valued numeric cells, etc.

Open issue: see `BUG-UNRESOLVED-HELPER-VALUE-NAN-SEMANTICS-P4A`.
"""

from __future__ import annotations

import json

import pytest


pytestmark = [
    pytest.mark.roundtrip,
    pytest.mark.ftr("FTR-ROUNDTRIP-TEST-LAYER-P4A"),
]


@pytest.mark.xfail(
    reason="BUG-UNRESOLVED-HELPER-VALUE-NAN-SEMANTICS-P4A: the framework "
    "currently has no defined contract for unresolved helper values. In the "
    "no-cleanup sentinel path used here, a missing FK key currently reimports "
    "with an ordinary empty-string helper value; the final representation may "
    "be null, a structured finding, a typed unresolved token, or another "
    "documented shape once the contract decision lands.",
    strict=False,
)
def test_missing_fk_key_helper_representation_without_cleanup(minimal_fk_workdir) -> None:
    """Unresolved helper values must have a defined canonical representation.

    The normal canonical reimport path now correctly drops helper
    columns, so it cannot exercise this value contract. This sentinel
    intentionally uses a no-cleanup reimport path to keep the helper
    column observable.

    ``ITEM-003`` is changed to reference ``ENT-MISSING`` before export.
    This is clearer than the empty-FK seed row: a lookup was requested,
    but the key cannot be resolved. The helper value must not become an
    ordinary domain string such as ``"nan"`` or ``""``. The final
    representation remains deliberately undecided by this BUG.
    """
    from tests.roundtrip.conftest import _run_cli, _write_yaml

    items_path = minimal_fk_workdir.canonical / "items.json"
    items = json.loads(items_path.read_text(encoding="utf-8"))
    items = [
        {**row, "entity_id": "ENT-MISSING"} if row.get("id") == "ITEM-003" else row
        for row in items
    ]
    items_path.write_text(json.dumps(items, indent=2), encoding="utf-8")

    assert minimal_fk_workdir.run_forward() == 0

    reimport = minimal_fk_workdir.root / "reimport_no_cleanup"
    reverse_yaml = minimal_fk_workdir.root / "reverse_no_cleanup.yaml"
    _write_yaml(
        reverse_yaml,
        {
            "io": {
                "input": {"kind": "xlsx", "path": str(minimal_fk_workdir.sheet)},
                "output": {"kind": "json_dir", "path": str(reimport)},
            },
            "pipeline": [
                {
                    "step": "apply_workbook_view_sheet_mappings",
                    "logical_frames": ["items", "entities"],
                },
            ],
        },
    )
    assert _run_cli(reverse_yaml) == 0

    items = json.loads((reimport / "items.json").read_text(encoding="utf-8"))
    unresolved = next(
        (row for row in items if row.get("entity_id") == "ENT-MISSING"),
        None,
    )
    assert unresolved is not None, (
        "fixture invariant: items.json must contain ITEM-003 with missing "
        "entity_id ENT-MISSING; the unresolved-helper contract test depends "
        "on this seed shape."
    )

    helper_column = "_entities_name"
    assert helper_column in unresolved, (
        "sentinel invariant: the no-cleanup reimport path must keep the "
        f"helper column {helper_column!r} observable; row was {unresolved!r}"
    )
    helper_value = unresolved[helper_column]

    assert helper_value not in ("nan", ""), (
        f"unresolved helper {helper_column!r} must not be serialized as an "
        f"ordinary scalar string; got value {helper_value!r} in row "
        f"{unresolved!r}"
    )
