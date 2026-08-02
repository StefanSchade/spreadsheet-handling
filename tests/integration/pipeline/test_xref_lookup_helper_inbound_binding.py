"""Slice 2 of FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2.

Proves the *inbound durable-provenance binding* that lets the lookup/helper
family replace ``project_by_role`` on import:

    visible workbook sheet
    -> apply_derived_column_policy(policy=drop), addressed by visible sheet name
    -> validate_references(no_helper_columns)          [postcondition]
    -> apply_workbook_view_sheet_mappings              [re-key to logical frame]
    -> expand_xref / expand_compact_multiaxis          [canonical inverse]

Settled facts this module exercises with existing public steps only (no new
runtime capability):

* the durable carrier ``_meta.sheets[<visible sheet>].helper_columns`` written
  by ``configure_workbook_view`` survives the persistence boundary;
* the transient ``_meta.derived`` ``enrich_lookup`` provenance does *not*
  survive the persistence boundary;
* after readback frames and durable sheet metadata are addressed by the visible
  sheet name, so cleanup must run *by visible sheet name before* the workbook
  view mapping re-keys frames to logical names;
* ``title`` is a read-only display helper: an edited value is dropped, not
  melted into the XRef relation and not written back to the lookup.

The persistence boundary is exercised through the orchestrator's own projection
function (``project_meta_to_persistable_contract``) plus the real XLSX and ODS
backends, so the "``_meta.derived`` is absent after readback" evidence is
produced by the maintained boundary rule, not hand-injected. Neutral synthetic
names are used rather than Dino-specific production fixtures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from spreadsheet_handling.pipeline import build_steps_from_config, run_pipeline
from spreadsheet_handling.pipeline.persistence_boundary import (
    project_meta_to_persistable_contract,
)

pytestmark = pytest.mark.ftr("FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2")

# ---------------------------------------------------------------------------
# Neutral synthetic identities
# ---------------------------------------------------------------------------

MATRIX_FRAME = "role_matrix"
LOOKUP_FRAME = "stories"
RELATION_FRAME = "role_relation"
VISIBLE_SHEET = "Matrix View"
LOOKUP_SHEET = "Story Lookup"
ROW_KEY = "story_id"
LOOKUP_KEY = "id"
HELPER = "title"
COLUMN_KEY = "character_name"
VALUE = "value"

_AXES = ["Alice", "Bob", "Carol"]

_EDITED_TITLE = "EDITED-TITLE-XYZ"


def _relation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {ROW_KEY: "s1", COLUMN_KEY: "Alice", VALUE: "hero"},
            {ROW_KEY: "s1", COLUMN_KEY: "Bob", VALUE: "sidekick"},
            {ROW_KEY: "s2", COLUMN_KEY: "Alice", VALUE: "villain"},
            {ROW_KEY: "s2", COLUMN_KEY: "Carol", VALUE: "extra"},
        ]
    )


def _stories() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {LOOKUP_KEY: "s1", HELPER: "First Story"},
            {LOOKUP_KEY: "s2", HELPER: "Second Story"},
        ]
    )


def _forward_config(*, declare_helper: bool = True) -> list[dict[str, Any]]:
    """Forward pipeline: contract -> add helper before key -> configure view.

    ``declare_helper`` toggles the ``helper_columns: [title]`` declaration on
    the workbook view sheet spec so the missing-declaration negative case can
    reuse the same forward shape.
    """
    matrix_sheet: dict[str, Any] = {"frame": MATRIX_FRAME, "sheet": VISIBLE_SHEET}
    if declare_helper:
        matrix_sheet["helper_columns"] = [HELPER]
    return [
        {
            "step": "contract_xref",
            "relation": RELATION_FRAME,
            "output": MATRIX_FRAME,
            "row_keys": [ROW_KEY],
            "column_key": COLUMN_KEY,
            "value": VALUE,
            "column_keys": _AXES,
            "name": "role",
        },
        {
            "step": "add_lookup_helpers",
            "source": MATRIX_FRAME,
            "lookup": LOOKUP_FRAME,
            "output": MATRIX_FRAME,
            "source_key": ROW_KEY,
            "lookup_key": LOOKUP_KEY,
            "helpers": {"fields": [HELPER]},
            "order": {"helper_position": "before_key"},
            "missing": "empty",
        },
        {
            "step": "configure_workbook_view",
            "sheets": [
                matrix_sheet,
                {"frame": LOOKUP_FRAME, "sheet": LOOKUP_SHEET},
            ],
        },
    ]


def _drop_step() -> dict[str, Any]:
    return {"step": "apply_derived_column_policy", "source": VISIBLE_SHEET, "policy": "drop"}


def _postcondition_step() -> dict[str, Any]:
    return {
        "step": "validate_references",
        "mode": "fail",
        "rules": [{"type": "no_helper_columns", "frame": VISIBLE_SHEET}],
    }


def _mapping_step() -> dict[str, Any]:
    return {
        "step": "apply_workbook_view_sheet_mappings",
        "logical_frames": [MATRIX_FRAME, LOOKUP_FRAME],
    }


def _expand_xref_step() -> dict[str, Any]:
    # No ``value_columns``: the dynamic matrix axes are inferred, never
    # enumerated in configuration (FTR non-goal: no static dynamic-column list).
    return {
        "step": "expand_xref",
        "matrix": MATRIX_FRAME,
        "output": RELATION_FRAME,
        "row_keys": [ROW_KEY],
        "column_key": COLUMN_KEY,
        "value": VALUE,
        "drop_empty": True,
        "name": "role",
    }


def _run_forward(config: list[dict[str, Any]]) -> dict[str, Any]:
    frames = {RELATION_FRAME: _relation(), LOOKUP_FRAME: _stories(), "_meta": {}}
    return run_pipeline(frames, build_steps_from_config(config))


def _persist_and_reload(
    forward: dict[str, Any], tmp_path: Path
) -> dict[str, dict[str, Any]]:
    """Project runtime meta at the real persistence boundary, then roundtrip.

    Mirrors the orchestrator macro flow: the same
    ``project_meta_to_persistable_contract`` the orchestrator calls immediately
    before the saver runs here, so ``_meta.derived`` is pruned by the
    maintained boundary rule (not by the test) before the XLSX and ODS backends
    write anything.
    """
    persistable = dict(forward)
    persistable["_meta"] = project_meta_to_persistable_contract(forward["_meta"])

    xlsx_path = tmp_path / "inbound-binding.xlsx"
    ods_path = tmp_path / "inbound-binding.ods"
    ExcelBackend().write_multi(persistable, str(xlsx_path))
    OdsBackend().write_multi(persistable, str(ods_path))
    return {
        "xlsx": ExcelBackend().read_multi(str(xlsx_path), header_levels=1),
        "ods": OdsBackend().read_multi(str(ods_path), header_levels=1),
    }


def _ordered(relation: pd.DataFrame) -> pd.DataFrame:
    return relation.sort_values([ROW_KEY, COLUMN_KEY], kind="mergesort").reset_index(
        drop=True
    )


# ---------------------------------------------------------------------------
# Forward shape and durable/transient provenance at the workbook boundary
# ---------------------------------------------------------------------------


def test_forward_materializes_helper_before_key_and_durable_declaration() -> None:
    forward = _run_forward(_forward_config())

    # add_lookup_helpers placed the display helper before the row key.
    assert list(forward[MATRIX_FRAME].columns) == [HELPER, ROW_KEY, *_AXES]

    # configure_workbook_view wrote the durable carrier keyed by *visible sheet*.
    assert forward["_meta"]["sheets"][VISIBLE_SHEET]["helper_columns"] == [HELPER]
    assert forward["_meta"]["workbook_view"]["sheet_mappings"] == [
        {"sheet": VISIBLE_SHEET, "frame": MATRIX_FRAME},
        {"sheet": LOOKUP_SHEET, "frame": LOOKUP_FRAME},
    ]

    # The transient enrich_lookup provenance exists in-run under the output name.
    assert (
        forward["_meta"]["derived"]["sheets"][MATRIX_FRAME]["enrich_lookup"][
            "helper_columns"
        ]
        == [HELPER]
    )


def test_persistence_boundary_strips_transient_keeps_durable(tmp_path: Path) -> None:
    forward = _run_forward(_forward_config())

    for backend_name, workbook in _persist_and_reload(forward, tmp_path).items():
        # Frames come back keyed by the visible sheet name, not the logical frame.
        assert VISIBLE_SHEET in workbook, backend_name
        assert MATRIX_FRAME not in workbook, backend_name

        # title is physically present in the payload sheet.
        assert HELPER in workbook[VISIBLE_SHEET].columns, backend_name

        # Transient lookup provenance was pruned by the persistence boundary.
        assert "derived" not in workbook["_meta"], backend_name

        # Durable workbook-view helper declaration survived under the visible sheet.
        assert (
            workbook["_meta"]["sheets"][VISIBLE_SHEET]["helper_columns"] == [HELPER]
        ), backend_name

        # The visible-to-logical identity is still declared for mapping.
        assert {
            entry["sheet"]: entry["frame"]
            for entry in workbook["_meta"]["workbook_view"]["sheet_mappings"]
        } == {VISIBLE_SHEET: MATRIX_FRAME, LOOKUP_SHEET: LOOKUP_FRAME}, backend_name


# ---------------------------------------------------------------------------
# Full inbound binding across XLSX and ODS (ordinary XRef inverse)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["xlsx", "ods"])
def test_inbound_binding_roundtrip_ordinary_xref(backend: str, tmp_path: Path) -> None:
    forward = _run_forward(_forward_config())
    workbook = _persist_and_reload(forward, tmp_path)[backend]

    # A business user edits one read-only title cell in the visible sheet.
    edited = workbook[VISIBLE_SHEET]
    edited.loc[edited[ROW_KEY] == "s1", HELPER] = _EDITED_TITLE
    assert _EDITED_TITLE in list(workbook[VISIBLE_SHEET][HELPER])

    # Snapshot the authoritative lookup for a later "unchanged" assertion.
    lookup_titles_before = list(workbook[LOOKUP_SHEET][HELPER])

    # Step 1: cleanup by visible sheet name removes the helper *before* mapping.
    dropped = run_pipeline(workbook, build_steps_from_config([_drop_step()]))
    assert HELPER not in dropped[VISIBLE_SHEET].columns
    assert VISIBLE_SHEET in dropped  # still keyed by the visible sheet name

    # Step 2: the no_helper_columns postcondition passes under mode=fail.
    validated = run_pipeline(dropped, build_steps_from_config([_postcondition_step()]))

    # Step 3: mapping re-keys the visible sheet to the logical frame.
    mapped = run_pipeline(validated, build_steps_from_config([_mapping_step()]))
    assert MATRIX_FRAME in mapped
    assert VISIBLE_SHEET not in mapped
    assert HELPER not in mapped[MATRIX_FRAME].columns

    # Step 4: the canonical inverse does not melt title and reproduces the relation.
    expanded = run_pipeline(mapped, build_steps_from_config([_expand_xref_step()]))
    relation = expanded[RELATION_FRAME]
    assert HELPER not in relation.columns
    assert HELPER not in relation[COLUMN_KEY].tolist()  # edited title not melted
    assert _EDITED_TITLE not in relation[VALUE].tolist()  # edited title discarded

    pd.testing.assert_frame_equal(
        _ordered(relation),
        _ordered(_relation()),
        check_dtype=False,
        obj=f"{backend} recomposed relation",
    )

    # The authoritative lookup title was never written back or mutated.
    assert list(expanded[LOOKUP_FRAME][HELPER]) == lookup_titles_before
    assert list(expanded[LOOKUP_FRAME][HELPER]) == ["First Story", "Second Story"]


# ---------------------------------------------------------------------------
# Compact-multiaxis inverse family (focused, no carrier roundtrip required)
# ---------------------------------------------------------------------------


def test_inbound_binding_compact_multiaxis_inverse() -> None:
    matrix = pd.DataFrame(
        [
            {ROW_KEY: "s1", "alpha_group": "C1", "beta_group": ""},
            {ROW_KEY: "s2", "alpha_group": "", "beta_group": "C2"},
        ]
    )
    frames = {"group_matrix": matrix, LOOKUP_FRAME: _stories(), "_meta": {}}

    forward = run_pipeline(
        frames,
        build_steps_from_config(
            [
                {
                    "step": "add_lookup_helpers",
                    "source": "group_matrix",
                    "lookup": LOOKUP_FRAME,
                    "output": "group_matrix",
                    "source_key": ROW_KEY,
                    "lookup_key": LOOKUP_KEY,
                    "helpers": {"fields": [HELPER]},
                    "order": {"helper_position": "before_key"},
                    "missing": "empty",
                },
                {
                    "step": "configure_workbook_view",
                    "sheets": [
                        {
                            "frame": "group_matrix",
                            "sheet": "Group View",
                            "helper_columns": [HELPER],
                        }
                    ],
                },
            ]
        ),
    )
    assert list(forward["group_matrix"].columns) == [
        HELPER,
        ROW_KEY,
        "alpha_group",
        "beta_group",
    ]

    # Simulate the post-boundary readback state: payload keyed by the visible
    # sheet, durable helper declaration present, transient provenance stripped.
    workbook = {
        "Group View": forward["group_matrix"],
        "_meta": {
            "sheets": {"Group View": {"helper_columns": [HELPER]}},
            "workbook_view": forward["_meta"]["workbook_view"],
        },
    }

    inbound = run_pipeline(
        workbook,
        build_steps_from_config(
            [
                {"step": "apply_derived_column_policy", "source": "Group View", "policy": "drop"},
                {
                    "step": "validate_references",
                    "mode": "fail",
                    "rules": [{"type": "no_helper_columns", "frame": "Group View"}],
                },
                {"step": "apply_workbook_view_sheet_mappings", "logical_frames": ["group_matrix"]},
                {
                    "step": "expand_compact_multiaxis",
                    "matrix": "group_matrix",
                    "output": "group_named",
                    "row_keys": [ROW_KEY],
                    "column_key": "group_name",
                    "code": "code",
                    "value": "value",
                    "mode": "whole_cell_code",
                    "allowed_codes": ["C1", "C2"],
                    "drop_empty": True,
                    "name": "grp",
                },
            ]
        ),
    )

    assert HELPER not in inbound["group_matrix"].columns
    assert inbound["group_named"].to_dict(orient="records") == [
        {ROW_KEY: "s1", "group_name": "alpha_group", "code": "C1"},
        {ROW_KEY: "s2", "group_name": "beta_group", "code": "C2"},
    ]


# ---------------------------------------------------------------------------
# Dynamic-axis genericity: two differing runtime column sets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "axes",
    [
        pytest.param(["Alpha", "Beta"], id="A"),
        pytest.param(["Beta", "Gamma", "Delta"], id="B"),
    ],
)
def test_dynamic_axis_genericity(axes: list[str], tmp_path: Path) -> None:
    relation_rows = []
    for story in ("s1", "s2"):
        for axis in axes:
            relation_rows.append(
                {ROW_KEY: story, COLUMN_KEY: axis, VALUE: f"{story}-{axis}"}
            )
    frames = {
        RELATION_FRAME: pd.DataFrame(relation_rows),
        LOOKUP_FRAME: _stories(),
        "_meta": {},
    }

    config = [
        {
            "step": "contract_xref",
            "relation": RELATION_FRAME,
            "output": MATRIX_FRAME,
            "row_keys": [ROW_KEY],
            "column_key": COLUMN_KEY,
            "value": VALUE,
            "column_keys": axes,
            "name": "dyn",
        },
        {
            "step": "add_lookup_helpers",
            "source": MATRIX_FRAME,
            "lookup": LOOKUP_FRAME,
            "output": MATRIX_FRAME,
            "source_key": ROW_KEY,
            "lookup_key": LOOKUP_KEY,
            "helpers": {"fields": [HELPER]},
            "order": {"helper_position": "before_key"},
            "missing": "empty",
        },
        {
            "step": "configure_workbook_view",
            "sheets": [
                {"frame": MATRIX_FRAME, "sheet": VISIBLE_SHEET, "helper_columns": [HELPER]},
                {"frame": LOOKUP_FRAME, "sheet": LOOKUP_SHEET},
            ],
        },
    ]
    forward = run_pipeline(frames, build_steps_from_config(config))
    assert list(forward[MATRIX_FRAME].columns) == [HELPER, ROW_KEY, *axes]

    workbook = _persist_and_reload(forward, tmp_path)["xlsx"]

    dropped = run_pipeline(workbook, build_steps_from_config([_drop_step()]))
    # Dynamic-column order is preserved after the helper drop.
    assert list(dropped[VISIBLE_SHEET].columns) == [ROW_KEY, *axes]

    inbound = run_pipeline(
        dropped,
        build_steps_from_config([_mapping_step(), _expand_xref_step()]),
    )
    pd.testing.assert_frame_equal(
        _ordered(inbound[RELATION_FRAME]),
        _ordered(frames[RELATION_FRAME]),
        check_dtype=False,
        obj=f"dynamic axes {axes}",
    )


# ---------------------------------------------------------------------------
# Ordering dependency and negative evidence
# ---------------------------------------------------------------------------


def test_wrong_order_mapping_before_cleanup_leaves_title(tmp_path: Path) -> None:
    """Mapping before cleanup cannot find the visible-sheet-keyed provenance.

    ``_meta.sheets`` is keyed by the visible sheet name and is *not* re-keyed by
    ``apply_workbook_view_sheet_mappings``. Dropping by the logical frame name
    after mapping therefore finds no durable helper declaration and leaves
    ``title`` in the frame, where the XRef inverse would melt it into the
    relation. This test demonstrates the risk that motivates the prescribed
    order; it does not celebrate the silent survival.
    """
    forward = _run_forward(_forward_config())
    workbook = _persist_and_reload(forward, tmp_path)["xlsx"]

    wrong_order = run_pipeline(
        workbook,
        build_steps_from_config(
            [
                _mapping_step(),
                {"step": "apply_derived_column_policy", "source": MATRIX_FRAME, "policy": "drop"},
            ]
        ),
    )
    # The helper survives because the durable provenance is unreachable under
    # the logical frame name.
    assert HELPER in wrong_order[MATRIX_FRAME].columns

    # Concrete downstream harm: the surviving helper is melted by the inverse.
    melted = run_pipeline(wrong_order, build_steps_from_config([_expand_xref_step()]))
    assert HELPER in melted[RELATION_FRAME][COLUMN_KEY].tolist()

    # The prescribed order (cleanup by visible sheet first) does drop it.
    correct_order = run_pipeline(workbook, build_steps_from_config([_drop_step()]))
    assert HELPER not in correct_order[VISIBLE_SHEET].columns


def test_missing_helper_declaration_leaves_title_unclassified(tmp_path: Path) -> None:
    """Without ``helper_columns: [title]`` the durable carrier is empty.

    Core cannot infer that ``title`` is a display helper from its name. When the
    workbook view omits the declaration, ``_meta.sheets`` carries no helper
    columns after readback, cleanup by visible sheet name is a safe no-op, and
    ``title`` stays unclassified and unsafe for the inverse. This makes the
    declaration dependency visible; it adds no name-based recovery.
    """
    forward = _run_forward(_forward_config(declare_helper=False))
    workbook = _persist_and_reload(forward, tmp_path)["xlsx"]

    # No durable helper declaration survived for the visible sheet.
    assert workbook["_meta"].get("sheets", {}).get(VISIBLE_SHEET, {}).get(
        "helper_columns"
    ) in (None, [])

    undropped = run_pipeline(workbook, build_steps_from_config([_drop_step()]))
    assert HELPER in undropped[VISIBLE_SHEET].columns  # title not classified/removed


# ---------------------------------------------------------------------------
# Postcondition guard behaviour and caller-state safety on failure
# ---------------------------------------------------------------------------


def test_no_helper_columns_postcondition_fails_when_helper_present(
    tmp_path: Path,
) -> None:
    """The postcondition is a real guard, not decoration.

    Running it *before* the drop (helper still present) must fail closed under
    ``mode=fail`` and must not mutate the caller frames or metadata.
    """
    forward = _run_forward(_forward_config())
    workbook = _persist_and_reload(forward, tmp_path)["xlsx"]

    before_columns = list(workbook[VISIBLE_SHEET].columns)
    before_meta_helpers = workbook["_meta"]["sheets"][VISIBLE_SHEET]["helper_columns"]

    with pytest.raises(ValueError, match="Helper columns must be absent"):
        run_pipeline(workbook, build_steps_from_config([_postcondition_step()]))

    # Caller state is unchanged by the failing validation.
    assert list(workbook[VISIBLE_SHEET].columns) == before_columns
    assert workbook["_meta"]["sheets"][VISIBLE_SHEET]["helper_columns"] == before_meta_helpers
    assert HELPER in workbook[VISIBLE_SHEET].columns
