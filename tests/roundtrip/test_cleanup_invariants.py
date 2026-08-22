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


def _forward_pipeline_config(canonical_dir, sheet_path, *, declare_helper_columns: bool):
    """Forward pipeline for the durable-cleanup-identity migration test.

    ``declare_helper_columns`` toggles the explicit, documented migration
    path (accepted design
    ``derived_artifact_deletion_authority_design_2026-08-21.adoc`` Section
    I): declaring ``helper_columns`` on the ``items`` sheet via
    ``configure_workbook_view`` is the durable, persistence-surviving
    cleanup-identity carrier a reimport pipeline needs when it does not run
    a fresh ``add_fk_helpers`` pass in the same session. Durable FK relation
    policy under ``_meta.helper_policies.fk`` is deliberately *not* that
    carrier (Slice 5): it identifies what FK would request, not what FK
    currently produced, so it no longer authorizes deletion on its own.
    """
    items_sheet: dict = {"frame": "items", "sheet": "items"}
    if declare_helper_columns:
        items_sheet["helper_columns"] = ["_entities_name"]
    return {
        "io": {
            "input": {"kind": "json_dir", "path": str(canonical_dir)},
            "output": {"kind": "xlsx", "path": str(sheet_path)},
        },
        "pipeline": [
            {
                "step": "configure_fk_helpers",
                "targets": {
                    "entities": {
                        "key": "id",
                        "allowed_helpers": ["name"],
                        "default_helpers": ["name"],
                        "helper_prefix": "_",
                        "fk_column": "entity_id",
                    }
                },
            },
            {
                "step": "add_fk_helpers",
                "defaults": {"levels": 2, "helper_value_mode": "values"},
            },
            {"step": "flatten_headers", "sheet": "items", "mode": "level0"},
            {
                "step": "configure_workbook_view",
                "sheets": [
                    items_sheet,
                    {"frame": "entities", "sheet": "entities"},
                ],
            },
        ],
    }


def _reverse_pipeline_config(sheet_path, reimport_dir):
    return {
        "io": {
            "input": {"kind": "xlsx", "path": str(sheet_path)},
            "output": {"kind": "json_dir", "path": str(reimport_dir)},
        },
        "pipeline": [
            {
                "step": "apply_workbook_view_sheet_mappings",
                "logical_frames": ["items", "entities"],
            },
            {"step": "apply_derived_column_policy", "source": "items", "policy": "drop"},
        ],
    }


@pytest.mark.ftr("BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A")
def test_helper_cleanup_survives_reimport_when_workbook_view_declares_helper_columns(
    minimal_fk_workdir,
) -> None:
    """The explicit, documented migration path still works (Slice 5).

    Transient ``_meta.derived`` has been stripped at the persistence
    boundary (the workbook -> canonical reimport itself), and no fresh
    ``add_fk_helpers`` pass runs in the reverse pipeline. Durable FK
    relation policy alone can no longer authorize cleanup (Slice 5), but
    the forward pipeline's explicit ``configure_workbook_view ...
    helper_columns: ["_entities_name"]`` declaration -- the durable,
    persistence-surviving cleanup-identity carrier this design retains --
    still does, via the unchanged ``_safe_durable_helper_names`` path.
    """
    from tests.roundtrip.conftest import _run_cli, _write_yaml

    forward_yaml = minimal_fk_workdir.root / "forward_with_view_helpers.yaml"
    reverse_yaml = minimal_fk_workdir.root / "reverse_view_helpers_cleanup.yaml"
    reimport = minimal_fk_workdir.root / "reimport_view_helpers_cleanup"

    _write_yaml(
        forward_yaml,
        _forward_pipeline_config(
            minimal_fk_workdir.canonical, minimal_fk_workdir.sheet, declare_helper_columns=True
        ),
    )
    _write_yaml(reverse_yaml, _reverse_pipeline_config(minimal_fk_workdir.sheet, reimport))

    assert _run_cli(forward_yaml) == 0
    assert _run_cli(reverse_yaml) == 0

    items = json.loads((reimport / "items.json").read_text(encoding="utf-8"))
    assert all("_entities_name" not in row for row in items)


@pytest.mark.ftr("BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A")
def test_helper_column_survives_reimport_when_only_durable_fk_policy_names_it(
    minimal_fk_workdir,
) -> None:
    """Fail-closed default (Slice 5, accepted deletion-authority design).

    Identical to the migration-path test above except the forward
    pipeline's ``configure_workbook_view`` step omits ``helper_columns``
    for ``items``, isolating durable FK relation policy as the only
    surviving cleanup-identity source for this sheet. Durable policy alone
    is no longer deletion authority (Section F/H): the generated helper
    column must now *survive* into reimported canonical JSON -- this is
    the same symptom class ``BUG-REIMPORT-PROMOTION-HELPER-COLUMN-LEAKAGE-P4A``
    was originally opened for, now demonstrating the new contract's
    fail-closed default exactly where the historical bug was discovered.
    """
    from tests.roundtrip.conftest import _run_cli, _write_yaml

    forward_yaml = minimal_fk_workdir.root / "forward_without_view_helpers.yaml"
    reverse_yaml = minimal_fk_workdir.root / "reverse_policy_cleanup.yaml"
    reimport = minimal_fk_workdir.root / "reimport_policy_cleanup"

    _write_yaml(
        forward_yaml,
        _forward_pipeline_config(
            minimal_fk_workdir.canonical, minimal_fk_workdir.sheet, declare_helper_columns=False
        ),
    )
    _write_yaml(reverse_yaml, _reverse_pipeline_config(minimal_fk_workdir.sheet, reimport))

    assert _run_cli(forward_yaml) == 0
    assert _run_cli(reverse_yaml) == 0

    items = json.loads((reimport / "items.json").read_text(encoding="utf-8"))
    assert any("_entities_name" in row for row in items)


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
