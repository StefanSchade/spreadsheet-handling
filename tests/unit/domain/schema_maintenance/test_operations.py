from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.schema_maintenance import (
    ColumnPlacement,
    ReorderSpec,
    SchemaMaintenanceRequest,
    SchemaOperationKind,
    add_column,
    apply_schema_maintenance,
    drop_column,
    rename_column,
    reorder_columns,
)

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": ["c1", "c2"],
            "name": ["Ada", "Ben"],
            "notes": ["first", "second"],
        }
    )


def _frames() -> dict[str, object]:
    return {
        "characters": _frame(),
        "_meta": {
            "derived": {
                "sheets": {
                    "characters": {
                        "helper_columns": [
                            {
                                "column": "stale_name",
                                "fk_column": "missing_fk",
                                "target": "places",
                            }
                        ]
                    }
                }
            }
        },
    }


def _request(
    kind: SchemaOperationKind,
    **overrides: object,
) -> SchemaMaintenanceRequest:
    values = {"kind": kind, "target_frame": "characters"}
    values.update(overrides)
    return SchemaMaintenanceRequest(**values)


def test_add_column_appends_default_value() -> None:
    frames = _frames()
    result = add_column(
        frames,
        _request(
            SchemaOperationKind.ADD_COLUMN,
            target_column="role",
            default_value="friend",
        ),
    )

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == ["id", "name", "notes", "role"]
    assert result.frames["characters"]["role"].tolist() == ["friend", "friend"]
    pd.testing.assert_frame_equal(frames["characters"], _frame())


def test_add_column_inserts_before_existing_column() -> None:
    result = add_column(
        _frames(),
        _request(
            SchemaOperationKind.ADD_COLUMN,
            target_column="kind",
            default_value="human",
            placement=ColumnPlacement(mode="before", column="name"),
        ),
    )

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == ["id", "kind", "name", "notes"]


def test_add_column_inserts_after_existing_column() -> None:
    result = add_column(
        _frames(),
        _request(
            SchemaOperationKind.ADD_COLUMN,
            target_column="kind",
            default_value="human",
            placement=ColumnPlacement(mode="after", column="name"),
        ),
    )

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == ["id", "name", "kind", "notes"]


def test_add_column_fails_if_target_column_exists() -> None:
    frames = _frames()
    result = add_column(
        frames,
        _request(SchemaOperationKind.ADD_COLUMN, target_column="name"),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "target_column_exists"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


def test_add_column_fails_on_unknown_placement_mode() -> None:
    frames = _frames()
    result = add_column(
        frames,
        _request(
            SchemaOperationKind.ADD_COLUMN,
            target_column="role",
            placement=ColumnPlacement(mode="middle", column="name"),
        ),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "invalid_placement_mode"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


@pytest.mark.parametrize("mode", ["before", "after"])
def test_add_column_before_after_fails_without_placement_column(mode: str) -> None:
    frames = _frames()
    result = add_column(
        frames,
        _request(
            SchemaOperationKind.ADD_COLUMN,
            target_column="role",
            placement=ColumnPlacement(mode=mode),
        ),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "missing_placement_column"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


@pytest.mark.parametrize("mode", ["before", "after"])
def test_add_column_before_after_fails_with_unknown_placement_column(mode: str) -> None:
    frames = _frames()
    result = add_column(
        frames,
        _request(
            SchemaOperationKind.ADD_COLUMN,
            target_column="role",
            placement=ColumnPlacement(mode=mode, column="missing"),
        ),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "placement_column_missing"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


def test_drop_column_removes_existing_column() -> None:
    result = drop_column(
        _frames(),
        _request(SchemaOperationKind.DROP_COLUMN, source_column="notes"),
    )

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == ["id", "name"]


def test_drop_column_fails_if_source_column_missing() -> None:
    frames = _frames()
    result = drop_column(
        frames,
        _request(SchemaOperationKind.DROP_COLUMN, source_column="missing"),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "source_column_missing"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


def test_rename_column_preserves_position_and_values() -> None:
    result = rename_column(
        _frames(),
        _request(
            SchemaOperationKind.RENAME_COLUMN,
            source_column="name",
            target_column="display_name",
        ),
    )

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == ["id", "display_name", "notes"]
    assert result.frames["characters"]["display_name"].tolist() == ["Ada", "Ben"]


def test_rename_column_fails_if_source_column_missing() -> None:
    frames = _frames()
    result = rename_column(
        frames,
        _request(
            SchemaOperationKind.RENAME_COLUMN,
            source_column="missing",
            target_column="display_name",
        ),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "source_column_missing"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


def test_rename_column_fails_if_target_column_exists() -> None:
    frames = _frames()
    result = rename_column(
        frames,
        _request(
            SchemaOperationKind.RENAME_COLUMN,
            source_column="notes",
            target_column="name",
        ),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "target_column_exists"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


def test_rename_worldbuilding_dotted_column() -> None:
    frames = {
        "characters": pd.DataFrame(
            {
                "id": ["c1", "c2"],
                "persona.crystal": ["quartz", "amber"],
                "notes": ["first", "second"],
            }
        )
    }

    result = rename_column(
        frames,
        _request(
            SchemaOperationKind.RENAME_COLUMN,
            source_column="persona.crystal",
            target_column="persona.focus_object",
        ),
    )

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == [
        "id",
        "persona.focus_object",
        "notes",
    ]
    assert result.frames["characters"]["persona.focus_object"].tolist() == ["quartz", "amber"]


def test_reorder_complete_success() -> None:
    result = reorder_columns(
        _frames(),
        _request(
            SchemaOperationKind.REORDER_COLUMNS,
            reorder=ReorderSpec(mode="complete", columns=("notes", "id", "name")),
        ),
    )

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == ["notes", "id", "name"]
    assert result.frames["characters"]["id"].tolist() == ["c1", "c2"]


def test_reorder_listed_first_success() -> None:
    result = reorder_columns(
        _frames(),
        _request(
            SchemaOperationKind.REORDER_COLUMNS,
            reorder=ReorderSpec(mode="listed_first", columns=("notes",)),
        ),
    )

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == ["notes", "id", "name"]


def test_reorder_listed_last_success() -> None:
    result = reorder_columns(
        _frames(),
        _request(
            SchemaOperationKind.REORDER_COLUMNS,
            reorder=ReorderSpec(mode="listed_last", columns=("id",)),
        ),
    )

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == ["name", "notes", "id"]


def test_reorder_fails_on_duplicate_requested_columns() -> None:
    frames = _frames()
    result = reorder_columns(
        frames,
        _request(
            SchemaOperationKind.REORDER_COLUMNS,
            reorder=ReorderSpec(mode="listed_first", columns=("name", "name")),
        ),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "duplicate_requested_columns"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


def test_reorder_fails_on_unknown_requested_column() -> None:
    frames = _frames()
    result = reorder_columns(
        frames,
        _request(
            SchemaOperationKind.REORDER_COLUMNS,
            reorder=ReorderSpec(mode="listed_first", columns=("missing",)),
        ),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "unknown_requested_columns"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


def test_reorder_fails_on_unknown_reorder_mode() -> None:
    frames = _frames()
    result = reorder_columns(
        frames,
        _request(
            SchemaOperationKind.REORDER_COLUMNS,
            reorder=ReorderSpec(mode="sideways", columns=("name",)),
        ),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "invalid_reorder_mode"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


def test_missing_target_frame_blocks_without_mutation() -> None:
    frames = _frames()
    result = add_column(
        frames,
        SchemaMaintenanceRequest(
            kind=SchemaOperationKind.ADD_COLUMN,
            target_frame="missing",
            target_column="role",
        ),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "missing_target_frame"
    assert set(result.frames) == set(frames)


def test_meta_is_passed_through_and_derived_does_not_influence_decisions() -> None:
    frames = _frames()
    result = rename_column(
        frames,
        _request(
            SchemaOperationKind.RENAME_COLUMN,
            source_column="name",
            target_column="display_name",
        ),
    )

    assert not result.report.blocked
    assert result.frames["_meta"] is frames["_meta"]
    assert "display_name" in result.frames["characters"].columns


def test_report_is_not_added_as_frame_or_stored_under_meta() -> None:
    result = add_column(
        _frames(),
        _request(SchemaOperationKind.ADD_COLUMN, target_column="role"),
    )

    assert "report" not in result.frames
    assert "schema_maintenance_report" not in result.frames
    assert "_schema_maintenance_report" not in result.frames
    assert "report" not in result.frames["_meta"]
    assert "schema_maintenance_report" not in result.frames["_meta"]
    assert "_schema_maintenance_report" not in result.frames["_meta"]


def test_named_operation_fails_on_request_kind_mismatch() -> None:
    frames = _frames()
    result = add_column(
        frames,
        _request(
            SchemaOperationKind.DROP_COLUMN,
            target_column="role",
        ),
    )

    assert result.report.blocked
    assert result.report.failures[0].code == "operation_kind_mismatch"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


@pytest.mark.parametrize(
    ("wrapper", "schema_request"),
    [
        (
            drop_column,
            _request(
                SchemaOperationKind.ADD_COLUMN,
                target_column="role",
            ),
        ),
        (
            rename_column,
            _request(
                SchemaOperationKind.DROP_COLUMN,
                source_column="name",
                target_column="display_name",
            ),
        ),
        (
            reorder_columns,
            _request(
                SchemaOperationKind.ADD_COLUMN,
                reorder=ReorderSpec(mode="listed_first", columns=("name",)),
            ),
        ),
    ],
)
def test_named_operations_fail_on_request_kind_mismatch(wrapper, schema_request) -> None:
    frames = _frames()
    result = wrapper(frames, schema_request)

    assert result.report.blocked
    assert result.report.failures[0].code == "operation_kind_mismatch"
    pd.testing.assert_frame_equal(result.frames["characters"], frames["characters"])


def test_apply_schema_maintenance_dispatches_by_request_kind() -> None:
    result = apply_schema_maintenance(
        _frames(),
        _request(
            SchemaOperationKind.RENAME_COLUMN,
            source_column="name",
            target_column="display_name",
        ),
    )

    assert not result.report.blocked
    assert list(result.frames["characters"].columns) == ["id", "display_name", "notes"]
