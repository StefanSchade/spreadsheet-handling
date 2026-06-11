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


def test_workbook_view_mapping_wins_when_sheet_name_collides_with_frame() -> None:
    frames = _matrix_frames()
    frames["story_groups"] = pd.DataFrame(
        {
            "canonical_id": ["c1"],
            "unrelated_value": ["not a matrix column"],
        }
    )

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
                },
            }
        ],
    )

    assert [constraint["column"] for constraint in frames["_meta"]["constraints"]] == [
        "Alpha",
        "Beta",
    ]


def test_roles_target_allows_sheet_name_is_frame_fallback() -> None:
    frames = {
        "matrix_view": pd.DataFrame(
            {
                "story_id": ["s1"],
                "title": ["Alpha story"],
                "Alpha": ["E"],
            }
        ),
        "_meta": {
            "xref_crosstable": {
                "story_group_matrix": {
                    "matrix": "matrix_view",
                    "row_keys": ["story_id"],
                },
            },
            "sheets": {
                "matrix_view": {"helper_columns": ["title"]},
            },
        },
    }

    add_validations(
        frames,
        rules=[
            {
                "sheet": "matrix_view",
                "roles": ["row_identity"],
                "rule": {"type": "in_list", "values": ["E"]},
            }
        ],
    )

    assert [constraint["column"] for constraint in frames["_meta"]["constraints"]] == [
        "story_id",
    ]


def test_explicit_frame_overrides_workbook_view_mapping() -> None:
    frames = _matrix_frames()
    frames["override_matrix_view"] = pd.DataFrame(
        {
            "story_id": ["s1"],
            "title": ["Override story"],
            "Gamma": ["E"],
        }
    )
    frames["_meta"]["xref_crosstable"]["override_matrix"] = {
        "matrix": "override_matrix_view",
        "row_keys": ["story_id"],
    }
    frames["_meta"]["workbook_view"]["sheets"].append(
        {
            "frame": "override_matrix_view",
            "sheet": "override_sheet",
            "order": 1,
        }
    )
    frames["_meta"]["sheets"]["override_sheet"] = {"helper_columns": ["title"]}

    add_validations(
        frames,
        rules=[
            {
                "target": {
                    "sheet": "story_groups",
                    "frame": "override_matrix_view",
                    "roles": ["matrix_value"],
                },
                "rule": {"type": "in_list", "values": ["E"]},
            }
        ],
    )

    assert frames["_meta"]["constraints"] == [
        {
            "sheet": "story_groups",
            "column": "Gamma",
            "rule": {"type": "in_list", "values": ["E"]},
            "on_violation": "error",
        }
    ]


@pytest.mark.ftr("BUG-GENERATED-META-CONSTRAINT-ACCUMULATION-P4A")
def test_flat_add_validations_deduplicates_existing_generated_constraint() -> None:
    frames: dict[str, object] = {
        "_meta": {
            "constraints": [
                {
                    "sheet": "audit",
                    "column": "status",
                    "rule": {"type": "in_list", "values": ["legacy"]},
                    "on_violation": "warn",
                },
                {
                    "sheet": "groups",
                    "column": "kind",
                    "rule": {"type": "in_list", "values": ["animal_group"]},
                    "on_violation": "error",
                },
                {
                    "sheet": "groups",
                    "column": "kind",
                    "rule": {"values": ["animal_group"], "type": "in_list"},
                    "on_violation": "error",
                },
            ]
        }
    }

    add_validations(
        frames,
        rules=[
            {
                "sheet": "groups",
                "column": "kind",
                "rule": {"type": "in_list", "values": ["animal_group"]},
            }
        ],
    )

    assert frames["_meta"]["constraints"] == [
        {
            "sheet": "audit",
            "column": "status",
            "rule": {"type": "in_list", "values": ["legacy"]},
            "on_violation": "warn",
        },
        {
            "sheet": "groups",
            "column": "kind",
            "rule": {"type": "in_list", "values": ["animal_group"]},
            "on_violation": "error",
        },
    ]


@pytest.mark.ftr("BUG-GENERATED-META-CONSTRAINT-ACCUMULATION-P4A")
def test_role_targeted_add_validations_deduplicates_expanded_constraints() -> None:
    frames = _matrix_frames()
    existing = [
        {
            "sheet": "story_groups",
            "column": "Alpha",
            "rule": {
                "include_empty": True,
                "legend": "story_group_codes",
                "type": "from_legend",
            },
            "on_violation": "error",
        },
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
    frames["_meta"]["constraints"] = existing

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

    assert [constraint["column"] for constraint in frames["_meta"]["constraints"]] == [
        "Alpha",
        "Beta",
    ]


@pytest.mark.ftr("BUG-GENERATED-META-CONSTRAINT-ACCUMULATION-P4A")
def test_add_validations_preserves_distinct_rules_for_same_column() -> None:
    frames: dict[str, object] = {
        "_meta": {
            "constraints": [
                {
                    "sheet": "groups",
                    "column": "kind",
                    "rule": {"type": "in_list", "values": ["animal_group"]},
                    "on_violation": "error",
                }
            ]
        }
    }

    add_validations(
        frames,
        rules=[
            {
                "sheet": "groups",
                "column": "kind",
                "rule": {"type": "in_list", "values": ["mythic_group"]},
            }
        ],
    )

    assert frames["_meta"]["constraints"] == [
        {
            "sheet": "groups",
            "column": "kind",
            "rule": {"type": "in_list", "values": ["animal_group"]},
            "on_violation": "error",
        },
        {
            "sheet": "groups",
            "column": "kind",
            "rule": {"type": "in_list", "values": ["mythic_group"]},
            "on_violation": "error",
        },
    ]


@pytest.mark.ftr("BUG-GENERATED-META-CONSTRAINT-ACCUMULATION-P4A")
def test_add_validations_preserves_distinct_on_violation_and_area() -> None:
    frames: dict[str, object] = {
        "_meta": {
            "constraints": [
                {
                    "sheet": "groups",
                    "column": "kind",
                    "rule": {"type": "in_list", "values": ["animal_group"]},
                    "on_violation": "warn",
                },
                {
                    "sheet": "groups",
                    "column": "kind",
                    "rule": {"type": "in_list", "values": ["animal_group"]},
                    "on_violation": "error",
                    "area": "A2:A10",
                },
            ]
        }
    }

    add_validations(
        frames,
        rules=[
            {
                "target": {
                    "sheet": "groups",
                    "column": "kind",
                    "area": "A2:A20",
                },
                "rule": {"type": "in_list", "values": ["animal_group"]},
            }
        ],
    )

    assert frames["_meta"]["constraints"] == [
        {
            "sheet": "groups",
            "column": "kind",
            "rule": {"type": "in_list", "values": ["animal_group"]},
            "on_violation": "warn",
        },
        {
            "sheet": "groups",
            "column": "kind",
            "rule": {"type": "in_list", "values": ["animal_group"]},
            "on_violation": "error",
            "area": "A2:A10",
        },
        {
            "sheet": "groups",
            "column": "kind",
            "rule": {"type": "in_list", "values": ["animal_group"]},
            "on_violation": "error",
            "area": "A2:A20",
        },
    ]
