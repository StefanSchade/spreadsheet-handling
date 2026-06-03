"""Cleanup invariants over the full canonical -> workbook -> canonical cycle.

Assert that helper-related cleanup intent declared in a reimport pipeline
actually holds at the canonical output, independently of *which step*
implements the invariant. Tests in this file must remain green across
refactors of the production code that provides the invariant.

Regression coverage for `BUG-HELPER-CLEANUP-CONTRACT-P4A`.
"""

from __future__ import annotations

import json

import pytest


pytestmark = [
    pytest.mark.roundtrip,
    pytest.mark.ftr("FTR-ROUNDTRIP-TEST-LAYER-P4A"),
]


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


def test_no_helper_columns_validation_reports_bypassed_cleanup(minimal_fk_workdir) -> None:
    """The recommended assertion rule must catch helper columns left behind."""
    from tests.roundtrip.conftest import _run_cli, _write_yaml

    assert minimal_fk_workdir.run_forward() == 0

    reimport = minimal_fk_workdir.root / "reimport_with_assertion_only"
    reverse_yaml = minimal_fk_workdir.root / "reverse_assertion_only.yaml"
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
                {
                    "step": "validate_references",
                    "rules": [{"type": "no_helper_columns", "frame": "items"}],
                },
            ],
        },
    )

    assert _run_cli(reverse_yaml) == 0
    findings = json.loads((reimport / "validation_findings.json").read_text(encoding="utf-8"))

    assert findings == [
        {
            "rule_type": "no_helper_columns",
            "frame": "items",
            "columns": "_entities_name",
            "row_index": "",
            "value": "",
            "target_frame": "",
            "target_columns": "",
            "severity": "warn",
            "message": "Helper columns must be absent after cleanup.",
        }
    ]
