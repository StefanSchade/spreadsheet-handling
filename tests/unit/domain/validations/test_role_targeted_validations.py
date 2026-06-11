from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.validations.validate_columns import add_validations


pytestmark = pytest.mark.ftr("FTR-DYNAMIC-VIEW-COLUMN-TARGETING-IMPL-P5")


def _matrix_frames() -> dict[str, object]:
    return {
        "story_group_matrix_view": pd.DataFrame(
            {
                "story_id": ["s1", "s2"],
                "title": ["Alpha story", "Beta story"],
                "Alpha": ["E", ""],
                "Beta": ["", "S"],
            }
        ),
        "_meta": {
            "xref_crosstable": {
                "story_group_matrix": {
                    "matrix": "story_group_matrix_view",
                    "row_keys": ["story_id"],
                },
            },
            "workbook_view": {
                "sheets": [
                    {
                        "frame": "story_group_matrix_view",
                        "sheet": "story_groups",
                        "order": 0,
                    },
                ],
            },
            "sheets": {
                "story_groups": {"helper_columns": ["title"]},
            },
        },
    }


def test_matrix_value_roles_fan_out_to_dynamic_columns() -> None:
    frames = _matrix_frames()

    add_validations(
        frames,
        rules=[
            {
                "target": {
                    "sheet": "story_groups",
                    "roles": ["matrix_value"],
                },
                "rule": {
                    "type": "from_legend",
                    "legend": "story_group_codes",
                    "include_empty": True,
                },
            }
        ],
    )

    assert frames["_meta"]["constraints"] == [
        {
            "sheet": "story_groups",
            "column": "Alpha",
            "rule": {
                "type": "from_legend",
                "legend": "story_group_codes",
                "include_empty": True,
            },
            "on_violation": "error",
        },
        {
            "sheet": "story_groups",
            "column": "Beta",
            "rule": {
                "type": "from_legend",
                "legend": "story_group_codes",
                "include_empty": True,
            },
            "on_violation": "error",
        },
    ]


def test_display_helper_role_targets_helper_columns() -> None:
    frames = _matrix_frames()

    add_validations(
        frames,
        rules=[
            {
                "sheet": "story_groups",
                "roles": ["display_helper"],
                "rule": {"type": "in_list", "values": ["Alpha story"]},
            }
        ],
    )

    assert frames["_meta"]["constraints"] == [
        {
            "sheet": "story_groups",
            "column": "title",
            "rule": {"type": "in_list", "values": ["Alpha story"]},
            "on_violation": "error",
        }
    ]


def test_unknown_role_fails_clearly() -> None:
    frames = _matrix_frames()

    with pytest.raises(ValueError, match="unknown role.*payload"):
        add_validations(
            frames,
            rules=[
                {
                    "sheet": "story_groups",
                    "roles": ["payload"],
                    "rule": {"type": "in_list", "values": ["x"]},
                }
            ],
        )


def test_roles_and_column_are_mutually_exclusive() -> None:
    frames = _matrix_frames()

    with pytest.raises(ValueError, match="must not combine 'roles'"):
        add_validations(
            frames,
            rules=[
                {
                    "sheet": "story_groups",
                    "column": "Alpha",
                    "roles": ["matrix_value"],
                    "rule": {"type": "in_list", "values": ["x"]},
                }
            ],
        )


def test_roles_and_columns_are_mutually_exclusive() -> None:
    frames = _matrix_frames()

    with pytest.raises(ValueError, match="must not combine 'roles'"):
        add_validations(
            frames,
            rules=[
                {
                    "target": {
                        "sheet": "story_groups",
                        "columns": ["Alpha"],
                        "roles": ["matrix_value"],
                    },
                    "rule": {"type": "in_list", "values": ["x"]},
                }
            ],
        )


def test_roles_target_requires_resolvable_frame() -> None:
    frames = {"Other": pd.DataFrame({"value": ["x"]}), "_meta": {}}

    with pytest.raises(ValueError, match="requires 'frame'"):
        add_validations(
            frames,
            rules=[
                {
                    "sheet": "story_groups",
                    "roles": ["matrix_value"],
                    "rule": {"type": "in_list", "values": ["x"]},
                }
            ],
        )
