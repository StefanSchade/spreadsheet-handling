from __future__ import annotations

import copy

import pandas as pd
import pytest

from spreadsheet_handling.domain.schema_maintenance import (
    ReferenceAction,
    ReferenceRoot,
    ReorderSpec,
    SchemaMaintenanceRequest,
    SchemaOperationKind,
    drop_column,
    rename_column,
    reorder_columns,
)

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def _base_frames(meta: object | None = None) -> dict[str, object]:
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
    # Frame-only routing: a sheet denotes exactly the frame mapped to it via
    # the "frame" key; sheet-scoped column references belong to the frame
    # actually rendered on that sheet.
    frames = _base_frames(
        {
            "workbook_view": {
                "sheet_mappings": [
                    {"sheet": "Characters", "frame": "characters"}
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


def test_rename_of_other_frame_leaves_sheet_scoped_references_of_mapped_frame() -> None:
    # Characterization of frame-only routing after canonical_frame removal:
    # the sheet resolves to the mapped view frame, so renaming a column of a
    # different frame (the former "canonical" source) neither updates nor
    # blocks the sheet-scoped reference. A legacy canonical_frame key on the
    # mapping is ignored and is not a resolution candidate.
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

    result = rename_column(frames, _rename(frame="characters"))

    assert not result.report.blocked
    assert result.frames["_meta"]["constraints"][0]["column"] == "name"


def test_legacy_canonical_frame_key_is_not_a_generic_structured_reference() -> None:
    frames = _base_frames(
        {
            "plugin_state": {
                "canonical_frame": "characters",
                "column": "name",
            }
        }
    )

    result = rename_column(frames, _rename(frame="characters"))

    assert not result.report.blocked
    assert result.frames["_meta"]["plugin_state"] == {
        "canonical_frame": "characters",
        "column": "name",
    }


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
    # Two explicit frame declarations disagree about which frame the sheet
    # denotes; resolution is ambiguous and the rename blocks.
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
                        "frame": "places",
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
                    {"sheet": "Characters", "frame": "characters"}
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


def test_fk_source_column_rename_updates_dotted_column_when_source_frame_matches() -> None:
    meta = _fk_meta()
    relation = meta["helper_policies"]["fk"]["relations"][0]
    relation["source_column"] = "persona.crystal"
    frames = _base_frames(meta)
    frames["characters"]["persona.crystal"] = ["quartz", "amber"]

    result = rename_column(
        frames,
        _rename(source="persona.crystal", target="persona.focus_object"),
    )

    assert not result.report.blocked
    relation = result.frames["_meta"]["helper_policies"]["fk"]["relations"][0]
    assert relation["source_column"] == "persona.focus_object"
    assert result.report.metadata_changes[0].path.endswith(".source_column")


def test_fk_target_field_rename_updates_dotted_column_when_target_frame_matches() -> None:
    meta = _fk_meta()
    relation = meta["helper_policies"]["fk"]["relations"][0]
    relation["helper_columns"][0]["target_field"] = "profile.title"
    frames = _base_frames(meta)
    frames["places"]["profile.title"] = ["Port", "Archive"]

    result = rename_column(
        frames,
        _rename(frame="places", source="profile.title", target="profile.display_title"),
    )

    assert not result.report.blocked
    relation = result.frames["_meta"]["helper_policies"]["fk"]["relations"][0]
    assert relation["helper_columns"][0]["target_field"] == "profile.display_title"
    assert result.report.metadata_changes[0].path.endswith(".helper_columns[0].target_field")


def test_fk_drop_blocks_dotted_source_column_reference() -> None:
    meta = _fk_meta()
    relation = meta["helper_policies"]["fk"]["relations"][0]
    relation["source_column"] = "persona.crystal"
    frames = _base_frames(meta)
    frames["characters"]["persona.crystal"] = ["quartz", "amber"]

    result = drop_column(
        frames,
        _drop(source="persona.crystal", prune=True),
    )

    assert result.report.blocked
    assert result.report.metadata_changes[0].action is ReferenceAction.BLOCKED
    assert result.report.failures[0].code == "blocking_metadata_reference"


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


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
def test_legacy_cell_codecs_payload_is_ignored_sediment() -> None:
    # The retired cell_codecs family has no producer or runtime reader;
    # legacy payloads are tolerated pass-through sediment whose stale
    # references must not block schema maintenance.
    frames = _base_frames(
        {
            "cell_codecs": {
                "legacy": {
                    "operation": "encode_cell_values",
                    "source": "characters",
                    "output": "characters_cells",
                    "group_by": ["id"],
                    "code": "name",
                    "value": "value",
                }
            }
        }
    )

    result = rename_column(frames, _rename())

    assert not result.report.blocked
    assert result.frames["_meta"]["cell_codecs"] == frames["_meta"]["cell_codecs"]


@pytest.mark.parametrize("root", ["compact_multiaxis"])
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


class TestXrefCrosstableReferences:
    """XRef intent is handled by a dedicated, feature-aware checker.

    Only the real reference shapes block: row_keys on the relation/matrix
    frames, run-local column_keys on the matrix frame, and dense-axis
    key(s) on the configured axis frame. Fabricated convention-style
    shapes and legacy descriptive fields are not references.
    """

    @staticmethod
    def _xref_meta(**overrides: object) -> dict:
        entry: dict = {
            "relation": "characters",
            "matrix": "characters_matrix",
            "row_keys": ["name"],
        }
        entry.update(overrides)
        return {"xref_crosstable": {"characters_view": entry}}

    def test_row_key_rename_on_relation_frame_blocks(self) -> None:
        result = rename_column(_base_frames(self._xref_meta()), _rename())

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"
        assert result.report.failures[0].meta_path == "xref_crosstable.characters_view"

    def test_row_key_drop_on_relation_frame_blocks(self) -> None:
        result = drop_column(_base_frames(self._xref_meta()), _drop(prune=True))

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"

    def test_dense_axis_key_rename_on_axis_frame_blocks(self) -> None:
        meta = self._xref_meta(
            row_keys=["id"],
            dense_axes={"rows_from": {"frame": "characters", "key": "name"}},
        )

        result = rename_column(_base_frames(meta), _rename())

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"

    def test_matrix_column_key_rename_blocks_only_on_matrix_frame(self) -> None:
        meta = {
            "xref_crosstable": {
                "characters_view": {
                    "relation": "places",
                    "matrix": "characters",
                    "row_keys": ["id"],
                    "column_keys": ["name"],
                }
            }
        }

        result = rename_column(_base_frames(meta), _rename())

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"

    def test_unreferenced_column_rename_passes_through(self) -> None:
        # Same column name on a frame the intent does not reference.
        meta = self._xref_meta(relation="places", matrix="places_matrix")

        result = rename_column(_base_frames(meta), _rename())

        assert not result.report.blocked
        assert result.frames["_meta"] == _base_frames(meta)["_meta"]

    def test_fabricated_convention_shape_is_not_a_reference(self) -> None:
        meta = {
            "xref_crosstable": {
                "story_matrix": {
                    "frame": "characters",
                    "value_column": "name",
                }
            }
        }

        result = rename_column(_base_frames(meta), _rename())

        assert not result.report.blocked

    def test_legacy_descriptive_fields_are_not_references(self) -> None:
        # Legacy payloads may still carry value/column_key descriptive
        # fields; they are ignored, not treated as column references.
        meta = self._xref_meta(
            relation="places",
            matrix="places_matrix",
            row_keys=["id"],
            value="name",
            column_key="name",
            operation="contract_xref",
        )

        result = rename_column(_base_frames(meta), _rename())

        assert not result.report.blocked

    def test_row_key_rename_on_matrix_frame_blocks(self) -> None:
        # The same row_keys list serves both sides; the matrix side blocks
        # exactly like the relation side.
        meta = {
            "xref_crosstable": {
                "characters_view": {
                    "relation": "places",
                    "matrix": "characters",
                    "row_keys": ["name"],
                }
            }
        }

        result = rename_column(_base_frames(meta), _rename())

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"

    def test_dense_axis_keys_plural_rename_on_axis_frame_blocks(self) -> None:
        meta = self._xref_meta(
            row_keys=["id"],
            dense_axes={"rows_from": {"frame": "characters", "keys": ["id", "name"]}},
        )

        result = rename_column(_base_frames(meta), _rename())

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"

    def test_resolved_column_keys_rename_blocks_on_matrix_frame(self) -> None:
        # A resolved-only hand-authored snapshot is a consumed fallback
        # (_resolve_dense_axes), so its column identities are real matrix
        # references.
        meta = {
            "xref_crosstable": {
                "characters_view": {
                    "relation": "places",
                    "matrix": "characters",
                    "row_keys": ["id"],
                    "dense_axes": {
                        "resolved": {"column_keys": ["name"]},
                    },
                }
            }
        }

        result = rename_column(_base_frames(meta), _rename())

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"

    def test_resolved_column_keys_drop_blocks_on_matrix_frame(self) -> None:
        meta = {
            "xref_crosstable": {
                "characters_view": {
                    "relation": "places",
                    "matrix": "characters",
                    "row_keys": ["id"],
                    "dense_axes": {
                        "resolved": {"column_keys": ["name"]},
                    },
                }
            }
        }

        result = drop_column(_base_frames(meta), _drop(prune=True))

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"

    def test_resolved_column_keys_on_other_frame_do_not_block(self) -> None:
        meta = {
            "xref_crosstable": {
                "characters_view": {
                    "relation": "characters",
                    "matrix": "places_matrix",
                    "row_keys": ["id"],
                    "dense_axes": {
                        "resolved": {"column_keys": ["name"]},
                    },
                }
            }
        }

        result = rename_column(_base_frames(meta), _rename())

        assert not result.report.blocked

    def test_malformed_xref_root_fails(self) -> None:
        result = rename_column(
            _base_frames({"xref_crosstable": ["not-a-mapping"]}), _rename()
        )

        assert result.report.blocked
        assert result.report.failures[0].code == "malformed_meta"

    def test_matrix_column_key_drop_blocks(self) -> None:
        meta = {
            "xref_crosstable": {
                "characters_view": {
                    "relation": "places",
                    "matrix": "characters",
                    "row_keys": ["id"],
                    "column_keys": ["name"],
                }
            }
        }

        result = drop_column(_base_frames(meta), _drop(prune=True))

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"

    def test_dense_columns_from_key_rename_on_axis_frame_blocks(self) -> None:
        meta = self._xref_meta(
            row_keys=["id"],
            dense_axes={"columns_from": {"frame": "characters", "key": "name"}},
        )

        result = rename_column(_base_frames(meta), _rename())

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"

    def test_dense_columns_from_keys_plural_drop_on_axis_frame_blocks(self) -> None:
        meta = self._xref_meta(
            row_keys=["id"],
            dense_axes={"columns_from": {"frame": "characters", "keys": ["name"]}},
        )

        result = drop_column(_base_frames(meta), _drop(prune=True))

        assert result.report.blocked
        assert result.report.failures[0].code == "blocking_metadata_reference"

    def test_blocked_xref_reference_does_not_mutate_input_metadata(self) -> None:
        import copy

        meta = self._xref_meta()
        frames = _base_frames(meta)
        snapshot = copy.deepcopy(frames["_meta"])

        result = rename_column(frames, _rename())

        assert result.report.blocked
        assert frames["_meta"] == snapshot
        assert result.frames["_meta"] == snapshot

    def test_non_mapping_individual_entry_is_tolerated(self) -> None:
        # Characterization: a non-mapping entry has no valid XRef reference
        # shape; runtime consumers skip it, and schema maintenance does the
        # same (tolerant-reader posture) instead of failing the whole root.
        meta = {
            "xref_crosstable": {
                "broken": "not-a-mapping",
                "valid": {
                    "relation": "places",
                    "matrix": "places_matrix",
                    "row_keys": ["id"],
                },
            }
        }

        result = rename_column(_base_frames(meta), _rename())

        assert not result.report.blocked


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


def test_meta_absent_operation_succeeds_without_metadata_changes() -> None:
    frames = _base_frames()

    result = rename_column(frames, _rename())

    assert not result.report.blocked
    assert "_meta" not in result.frames
    assert result.report.metadata_changes == ()


def test_reorder_with_metadata_does_not_rewrite_or_block_metadata() -> None:
    meta = {
        "constraints": [
            {"sheet": "characters", "column": "name", "rule": {"type": "in_list"}}
        ],
        "sheets": {
            "characters": {
                "helper_columns": ["home_place_id"],
                "protection": {"editable_columns": ["name", "notes"]},
            }
        },
        "helper_policies": {
            "fk": {
                "schema_version": 2,
                "relations": [
                    {
                        "source_frame": "characters",
                        "source_column": "home_place_id",
                        "target_frame": "places",
                        "target_key": "id",
                    }
                ],
            }
        },
        "derived": {"sheets": {"characters": {"helper_columns": ["runtime_only"]}}},
    }
    frames = _base_frames(meta)

    result = reorder_columns(
        frames,
        SchemaMaintenanceRequest(
            kind=SchemaOperationKind.REORDER_COLUMNS,
            target_frame="characters",
            reorder=ReorderSpec(
                mode="complete",
                columns=("notes", "home_place_id", "name", "id"),
            ),
        ),
    )

    assert not result.report.blocked
    assert result.frames["characters"].columns.tolist() == ["notes", "home_place_id", "name", "id"]
    assert result.frames["_meta"] is frames["_meta"]
    assert [change.action for change in result.report.metadata_changes] == [
        ReferenceAction.IGNORED_DERIVED
    ]


@pytest.mark.parametrize(
    ("meta", "expected_path"),
    [
        ("not-a-mapping", "_meta"),
        ({"constraints": "not-a-list"}, "constraints"),
        ({"constraints": ["not-a-mapping"]}, "constraints[0]"),
        ({"sheets": "not-a-mapping"}, "sheets"),
        ({"sheets": {"characters": "not-a-mapping"}}, "sheets.characters"),
        (
            {"helper_policies": {"fk": {"relations": "not-a-list"}}},
            "helper_policies.fk.relations",
        ),
        ({"workbook_view": "not-a-mapping"}, "workbook_view"),
        ({"workbook_view": {"sheet_mappings": "not-a-list"}}, "workbook_view.sheet_mappings"),
        ({"workbook_view": {"sheets": "not-a-list"}}, "workbook_view.sheets"),
    ],
)
def test_malformed_meta_shapes_block_safely(meta: object, expected_path: str) -> None:
    frames = _base_frames(meta)
    original_columns = frames["characters"].columns.tolist()

    result = rename_column(frames, _rename())

    assert result.report.blocked
    assert result.report.failures[0].code == "malformed_meta"
    assert result.report.failures[0].meta_path == expected_path
    assert result.frames["characters"].columns.tolist() == original_columns


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


def _lookup_meta() -> dict:
    return {
        "helper_policies": {
            "lookup": {
                "places": {
                    "key": "id",
                    "allowed_helpers": ["name"],
                    "default_helpers": ["name"],
                    "missing": "fail",
                    "order": {"sort_by": ["name"]},
                }
            }
        }
    }


def test_rename_updates_lookup_policy_columns_for_the_lookup_frame() -> None:
    frames = _base_frames(_lookup_meta())

    result = rename_column(frames, _rename(frame="places", source="name", target="label"))

    assert not result.report.blocked
    policy = result.frames["_meta"]["helper_policies"]["lookup"]["places"]
    assert policy["allowed_helpers"] == ["label"]
    assert policy["default_helpers"] == ["label"]
    assert policy["order"]["sort_by"] == ["label"]
    assert policy["missing"] == "fail"
    assert {change.path for change in result.report.metadata_changes} == {
        "helper_policies.lookup.places.allowed_helpers",
        "helper_policies.lookup.places.default_helpers",
        "helper_policies.lookup.places.order.sort_by",
    }
    assert all(
        change.root is ReferenceRoot.HELPER_POLICIES_LOOKUP
        and change.action is ReferenceAction.UPDATED
        for change in result.report.metadata_changes
    )


def test_rename_updates_lookup_policy_scalar_key() -> None:
    frames = _base_frames(_lookup_meta())

    result = rename_column(frames, _rename(frame="places", source="id", target="place_id"))

    assert not result.report.blocked
    policy = result.frames["_meta"]["helper_policies"]["lookup"]["places"]
    assert policy["key"] == "place_id"
    assert result.report.metadata_changes[0].path == "helper_policies.lookup.places.key"


def test_rename_updates_lookup_policy_composite_key_and_scalar_sort_by() -> None:
    meta = _lookup_meta()
    meta["helper_policies"]["lookup"]["places"]["key"] = ["id", "name"]
    meta["helper_policies"]["lookup"]["places"]["order"] = {"sort_by": "name"}
    frames = _base_frames(meta)

    result = rename_column(frames, _rename(frame="places", source="name", target="label"))

    assert not result.report.blocked
    policy = result.frames["_meta"]["helper_policies"]["lookup"]["places"]
    assert policy["key"] == ["id", "label"]
    assert policy["order"]["sort_by"] == "label"


def test_rename_leaves_lookup_policies_of_other_frames_untouched() -> None:
    frames = _base_frames(_lookup_meta())

    result = rename_column(frames, _rename(frame="characters", source="name", target="display_name"))

    assert not result.report.blocked
    assert result.frames["_meta"]["helper_policies"]["lookup"] == (
        _lookup_meta()["helper_policies"]["lookup"]
    )
    assert not [
        change
        for change in result.report.metadata_changes
        if change.root is ReferenceRoot.HELPER_POLICIES_LOOKUP
    ]


def test_lookup_drop_blocks_even_when_prune_is_requested() -> None:
    frames = _base_frames(_lookup_meta())

    result = drop_column(frames, _drop(frame="places", source="name", prune=True))

    assert result.report.blocked
    blocked = [
        change
        for change in result.report.metadata_changes
        if change.action is ReferenceAction.BLOCKED
    ]
    assert {change.path for change in blocked} == {
        "helper_policies.lookup.places.allowed_helpers",
        "helper_policies.lookup.places.default_helpers",
        "helper_policies.lookup.places.order.sort_by",
    }
    assert {failure.code for failure in result.report.failures} == {"blocking_metadata_reference"}
    assert result.frames["_meta"] == frames["_meta"]
    assert list(result.frames["places"].columns) == ["id", "name"]


def test_lookup_policy_does_not_block_unreferenced_drop() -> None:
    frames = _base_frames(_lookup_meta())

    result = drop_column(frames, _drop(frame="characters", source="notes"))

    assert not result.report.blocked
    assert "notes" not in result.frames["characters"].columns
    assert result.frames["_meta"]["helper_policies"]["lookup"] == (
        _lookup_meta()["helper_policies"]["lookup"]
    )


def test_malformed_lookup_policy_shapes_block_safely() -> None:
    meta = {"helper_policies": {"lookup": {"places": {"key": {"bad": "shape"}}}}}
    frames = _base_frames(meta)

    result = rename_column(frames, _rename(frame="places", source="id", target="place_id"))

    assert result.report.blocked
    assert result.report.failures[0].code == "malformed_meta"
    assert result.report.failures[0].meta_path == "helper_policies.lookup.places.key"
    assert result.frames["_meta"] == meta


def _future_plugin_meta(frame: str = "characters", column: str = "name") -> dict:
    return {
        "helper_policies": {
            "future_plugin": {
                "targets": [{"frame": frame, "column": column}],
            }
        }
    }


def test_rename_blocks_unhandled_helper_policy_subtree_with_conventional_reference() -> None:
    frames = _base_frames(_future_plugin_meta())

    result = rename_column(frames, _rename())

    assert result.report.blocked
    blocked = result.report.metadata_changes[-1]
    assert blocked.action is ReferenceAction.BLOCKED
    assert blocked.root is ReferenceRoot.UNKNOWN_PLUGIN
    assert blocked.path == "helper_policies.future_plugin"
    assert result.report.failures[0].code == "blocking_metadata_reference"
    assert result.frames["_meta"] == frames["_meta"]
    assert list(result.frames["characters"].columns) == ["id", "name", "home_place_id", "notes"]


def test_drop_blocks_unhandled_helper_policy_subtree_with_conventional_reference() -> None:
    frames = _base_frames(_future_plugin_meta())

    result = drop_column(frames, _drop(source="name", prune=True))

    assert result.report.blocked
    assert result.report.failures[0].code == "blocking_metadata_reference"
    assert result.report.failures[0].meta_path == "helper_policies.future_plugin"
    assert result.frames["_meta"] == frames["_meta"]
    assert "name" in result.frames["characters"].columns


def test_unhandled_helper_policy_subtree_without_matching_reference_does_not_block() -> None:
    # References another frame's column and an unrelated column of the target
    # frame: neither matches (frame, affected column), so the operation stays
    # non-invasive for the unmaintained subtree.
    meta = {
        "helper_policies": {
            "future_plugin": {
                "targets": [
                    {"frame": "places", "column": "name"},
                    {"frame": "characters", "column": "notes"},
                ],
            }
        }
    }
    frames = _base_frames(meta)

    result = rename_column(frames, _rename())

    assert not result.report.blocked
    assert result.frames["_meta"]["helper_policies"] == meta["helper_policies"]
    assert "display_name" in result.frames["characters"].columns


def test_handled_fk_and_lookup_subtrees_stay_maintained_next_to_unhandled_ones() -> None:
    meta = _fk_meta()
    meta["helper_policies"]["lookup"] = _lookup_meta()["helper_policies"]["lookup"]
    meta["helper_policies"]["future_plugin"] = {
        "targets": [{"frame": "places", "column": "id"}]
    }
    frames = _base_frames(meta)

    result = rename_column(frames, _rename(frame="places", source="name", target="label"))

    assert not result.report.blocked
    relation = result.frames["_meta"]["helper_policies"]["fk"]["relations"][0]
    assert relation["helper_columns"][0]["target_field"] == "label"
    policy = result.frames["_meta"]["helper_policies"]["lookup"]["places"]
    assert policy["allowed_helpers"] == ["label"]
    assert result.frames["_meta"]["helper_policies"]["future_plugin"] == (
        meta["helper_policies"]["future_plugin"]
    )
