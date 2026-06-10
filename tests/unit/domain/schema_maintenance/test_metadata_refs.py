from __future__ import annotations

import copy

import pandas as pd
import pytest

from spreadsheet_handling.domain.schema_maintenance import (
    ReferenceAction,
    ReferenceRoot,
    SchemaMaintenanceRequest,
    SchemaOperationKind,
    drop_column,
    rename_column,
)

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def _base_frames(meta: dict | None = None) -> dict[str, object]:
    frames: dict[str, object] = {
        "characters": pd.DataFrame(
            {
                "id": ["c1", "c2"],
                "name": ["Ada", "Ben"],
                "home_place_id": ["p1", "p2"],
                "notes": ["first", "second"],
            }
        ),
        "places": pd.DataFrame(
            {
                "id": ["p1", "p2"],
                "name": ["Harbor", "Library"],
            }
        ),
    }
    if meta is not None:
        frames["_meta"] = meta
    return frames


def _rename(
    frame: str = "characters",
    source: str = "name",
    target: str = "display_name",
) -> SchemaMaintenanceRequest:
    return SchemaMaintenanceRequest(
        kind=SchemaOperationKind.RENAME_COLUMN,
        target_frame=frame,
        source_column=source,
        target_column=target,
    )


def _drop(
    frame: str = "characters",
    source: str = "name",
    *,
    prune: bool = False,
) -> SchemaMaintenanceRequest:
    return SchemaMaintenanceRequest(
        kind=SchemaOperationKind.DROP_COLUMN,
        target_frame=frame,
        source_column=source,
        prune=prune,
    )


def _fk_meta() -> dict:
    return {
        "helper_policies": {
            "fk": {
                "schema_version": 2,
                "relations": [
                    {
                        "source_frame": "characters",
                        "source_column": "home_place_id",
                        "target_frame": "places",
                        "target_key": "id",
                        "helper_columns": [
                            {
                                "column": "_places_name",
                                "target_field": "name",
                            }
                        ],
                    }
                ],
            }
        }
    }


def test_rename_updates_constraints_column_when_sheet_matches_target_frame() -> None:
    frames = _base_frames(
        {
            "constraints": [
                {"sheet": "characters", "column": "name", "rule": {"type": "in_list"}}
            ]
        }
    )

    result = rename_column(frames, _rename())

    assert not result.report.blocked
    assert result.frames["_meta"]["constraints"][0]["column"] == "display_name"
    assert result.report.metadata_changes[0].root is ReferenceRoot.CONSTRAINTS
    assert result.report.metadata_changes[0].action is ReferenceAction.UPDATED


def test_rename_updates_constraints_column_when_sheet_mapping_resolves_target_frame() -> None:
    frames = _base_frames(
        {
            "workbook_view": {
                "sheet_mappings": [
                    {
                        "sheet": "Characters",
                        "frame": "characters_view",
                        "canonical_frame": "characters",
                    }
                ]
            },
            "constraints": [
                {"sheet": "Characters", "column": "name", "rule": {"type": "in_list"}}
            ],
        }
    )

    result = rename_column(frames, _rename())

    assert not result.report.blocked
    assert result.frames["_meta"]["constraints"][0]["column"] == "display_name"


def test_rename_updates_constraints_column_when_workbook_view_sheets_resolves_target_frame() -> None:
    frames = _base_frames(
        {
            "workbook_view": {
                "sheets": [
                    {
                        "sheet": "Characters",
                        "frame": "characters",
                    }
                ]
            },
            "constraints": [
                {"sheet": "Characters", "column": "name", "rule": {"type": "in_list"}}
            ],
        }
    )

    result = rename_column(frames, _rename())

    assert not result.report.blocked
    assert result.frames["_meta"]["constraints"][0]["column"] == "display_name"


def test_rename_blocks_conflicting_workbook_view_sheet_resolution() -> None:
    frames = _base_frames(
        {
            "workbook_view": {
                "sheets": [
                    {
                        "sheet": "Characters",
                        "frame": "characters",
                    }
                ],
                "sheet_mappings": [
                    {
                        "sheet": "Characters",
                        "canonical_frame": "places",
                    }
                ],
            },
            "constraints": [
                {"sheet": "Characters", "column": "name", "rule": {"type": "in_list"}}
            ],
        }
    )

    result = rename_column(frames, _rename())

    assert result.report.blocked
    assert result.report.failures[0].code == "ambiguous_metadata_reference"
    assert list(result.frames["characters"].columns) == ["id", "name", "home_place_id", "notes"]


def test_rename_blocks_ambiguous_constraints_sheet_resolution() -> None:
    frames = _base_frames(
        {
            "constraints": [
                {"sheet": "Characters", "column": "name", "rule": {"type": "in_list"}}
            ]
        }
    )
    original_meta = copy.deepcopy(frames["_meta"])

    result = rename_column(frames, _rename())

    assert result.report.blocked
    assert result.report.failures[0].code == "ambiguous_metadata_reference"
    assert list(result.frames["characters"].columns) == ["id", "name", "home_place_id", "notes"]
    assert result.frames["_meta"] == original_meta


def test_drop_blocks_constraint_reference_by_default() -> None:
    frames = _base_frames(
        {
            "constraints": [
                {"sheet": "characters", "column": "name", "rule": {"type": "in_list"}}
            ]
        }
    )

    result = drop_column(frames, _drop())

    assert result.report.blocked
    assert result.report.failures[0].code == "blocking_metadata_reference"
    assert list(result.frames["characters"].columns) == ["id", "name", "home_place_id", "notes"]


def test_drop_with_prune_removes_supported_constraint_reference() -> None:
    frames = _base_frames(
        {
            "constraints": [
                {"sheet": "characters", "column": "name", "rule": {"type": "in_list"}},
                {"sheet": "characters", "column": "notes", "rule": {"type": "in_list"}},
            ]
        }
    )

    result = drop_column(frames, _drop(prune=True))

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == ["id", "home_place_id", "notes"]
    assert result.frames["_meta"]["constraints"] == [
        {"sheet": "characters", "column": "notes", "rule": {"type": "in_list"}}
    ]
    assert result.report.metadata_changes[0].action is ReferenceAction.PRUNED


def test_rename_updates_supported_sheet_helper_and_editable_columns() -> None:
    frames = _base_frames(
        {
            "workbook_view": {
                "sheet_mappings": [
                    {"sheet": "Characters", "canonical_frame": "characters"}
                ]
            },
            "sheets": {
                "Characters": {
                    "helper_columns": ["name"],
                    "protection": {"editable_columns": ["notes", "name"]},
                }
            },
        }
    )

    result = rename_column(frames, _rename())

    assert not result.report.blocked
    sheet_meta = result.frames["_meta"]["sheets"]["Characters"]
    assert sheet_meta["helper_columns"] == ["display_name"]
    assert sheet_meta["protection"]["editable_columns"] == ["notes", "display_name"]
    assert [change.action for change in result.report.metadata_changes] == [
        ReferenceAction.UPDATED,
        ReferenceAction.UPDATED,
    ]


def test_fk_source_column_rename_updates_only_when_source_frame_matches() -> None:
    frames = _base_frames(_fk_meta())

    result = rename_column(
        frames,
        _rename(source="home_place_id", target="place_id"),
    )

    assert not result.report.blocked
    relation = result.frames["_meta"]["helper_policies"]["fk"]["relations"][0]
    assert relation["source_column"] == "place_id"
    assert relation["target_key"] == "id"
    assert result.report.metadata_changes[0].path.endswith(".source_column")


def test_fk_target_key_and_target_field_rename_updates_only_when_target_frame_matches() -> None:
    meta = _fk_meta()
    relation = meta["helper_policies"]["fk"]["relations"][0]
    relation["target_key"] = "name"
    frames = _base_frames(meta)

    result = rename_column(
        frames,
        _rename(frame="places", source="name", target="label"),
    )

    assert not result.report.blocked
    relation = result.frames["_meta"]["helper_policies"]["fk"]["relations"][0]
    assert relation["target_key"] == "label"
    assert relation["helper_columns"][0]["target_field"] == "label"
    assert [change.path for change in result.report.metadata_changes] == [
        "helper_policies.fk.relations[0].target_key",
        "helper_policies.fk.relations[0].helper_columns[0].target_field",
    ]


def test_fk_drop_blocks_even_when_prune_is_requested() -> None:
    frames = _base_frames(_fk_meta())

    result = drop_column(
        frames,
        _drop(source="home_place_id", prune=True),
    )

    assert result.report.blocked
    assert result.report.metadata_changes[0].action is ReferenceAction.BLOCKED
    assert result.frames["_meta"] == frames["_meta"]
    assert list(result.frames["characters"].columns) == ["id", "name", "home_place_id", "notes"]


@pytest.mark.parametrize("root", ["compact_multiaxis", "xref_crosstable"])
def test_detected_transformation_structured_reference_blocks(root: str) -> None:
    frames = _base_frames(
        {
            root: {
                "story_matrix": {
                    "frame": "characters",
                    "value_column": "name",
                }
            }
        }
    )

    result = rename_column(frames, _rename())

    assert result.report.blocked
    assert result.report.metadata_changes[0].action is ReferenceAction.BLOCKED
    assert result.report.failures[0].code == "blocking_metadata_reference"


def test_derived_does_not_enable_rename_and_is_not_rewritten_as_canonical_metadata() -> None:
    frames = _base_frames(
        {
            "derived": {
                "sheets": {
                    "characters": {
                        "helper_columns": [
                            {"column": "missing_column", "fk_column": "id", "target": "places"}
                        ]
                    }
                }
            }
        }
    )

    result = rename_column(frames, _rename(source="missing_column", target="new_column"))

    assert result.report.blocked
    assert result.report.failures[0].code == "source_column_missing"
    assert result.frames["_meta"] == frames["_meta"]


def test_derived_is_reported_ignored_but_not_rewritten() -> None:
    meta = {"derived": {"sheets": {"characters": {"helper_columns": []}}}}
    frames = _base_frames(meta)

    result = rename_column(frames, _rename())

    assert not result.report.blocked
    assert result.frames["_meta"] is frames["_meta"]
    assert result.report.metadata_changes[0].root is ReferenceRoot.DERIVED
    assert result.report.metadata_changes[0].action is ReferenceAction.IGNORED_DERIVED


def test_unknown_non_structured_metadata_root_is_not_heuristically_scanned_or_rewritten() -> None:
    frames = _base_frames(
        {
            "plugin_notes": {
                "text": "characters.name appears here but is not a structured reference"
            }
        }
    )

    result = rename_column(frames, _rename())

    assert not result.report.blocked
    assert result.frames["_meta"]["plugin_notes"] == frames["_meta"]["plugin_notes"]


def test_plugin_owned_structured_frame_column_reference_blocks() -> None:
    frames = _base_frames(
        {
            "plugin_policy": {
                "frame": "characters",
                "column": "name",
            }
        }
    )

    result = rename_column(frames, _rename())

    assert result.report.blocked
    assert result.report.metadata_changes[0].root is ReferenceRoot.UNKNOWN_PLUGIN
    assert result.report.metadata_changes[0].action is ReferenceAction.BLOCKED


def test_report_is_still_not_added_as_frame_or_under_meta() -> None:
    frames = _base_frames(
        {
            "constraints": [
                {"sheet": "characters", "column": "name", "rule": {"type": "in_list"}}
            ]
        }
    )

    result = rename_column(frames, _rename())

    assert not result.report.blocked
    assert "report" not in result.frames
    assert "schema_maintenance_report" not in result.frames
    assert "_schema_maintenance_report" not in result.frames
    assert "report" not in result.frames["_meta"]
    assert "schema_maintenance_report" not in result.frames["_meta"]
    assert "_schema_maintenance_report" not in result.frames["_meta"]
