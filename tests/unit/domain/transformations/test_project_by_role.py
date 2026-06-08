from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.project_by_role import (
    project_by_role,
)


pytestmark = pytest.mark.ftr("FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5")


def _story_group_matrix_view() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "story_id": ["s1", "s2"],
            "Alpha": ["E", ""],
            "title": ["Alpha story", "Beta story"],
            "Beta": ["", "S"],
        }
    )


def _frames_with_overrides_required() -> dict[str, object]:
    return {
        "story_group_matrix_view": _story_group_matrix_view(),
    }


# ---------------------------------------------------------------------------
# Outbound semantics
# ---------------------------------------------------------------------------


def test_outbound_default_order_is_helpers_then_keys_then_matrix_values() -> None:
    frames = _frames_with_overrides_required()

    out = project_by_role(
        frames,
        frame="story_group_matrix_view",
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert list(out["story_group_matrix_view"].columns) == [
        "title",
        "story_id",
        "Alpha",
        "Beta",
    ]


def test_outbound_within_role_order_follows_input_order() -> None:
    frames = {
        "matrix_view": pd.DataFrame(
            {
                "Beta": ["x"],
                "story_id": ["s1"],
                "title": ["A"],
                "Alpha": ["y"],
            }
        ),
    }

    out = project_by_role(
        frames,
        frame="matrix_view",
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert list(out["matrix_view"].columns) == ["title", "story_id", "Beta", "Alpha"]


def test_outbound_custom_role_order_respected() -> None:
    frames = _frames_with_overrides_required()

    out = project_by_role(
        frames,
        frame="story_group_matrix_view",
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
        role_order=["row_identity", "display_helper", "matrix_value"],
    )

    assert list(out["story_group_matrix_view"].columns) == [
        "story_id",
        "title",
        "Alpha",
        "Beta",
    ]


def test_outbound_role_order_with_unknown_role_raises() -> None:
    frames = _frames_with_overrides_required()

    with pytest.raises(ValueError, match="unknown role"):
        project_by_role(
            frames,
            frame="story_group_matrix_view",
            direction="outbound",
            helper_columns=["title"],
            key_columns=["story_id"],
            role_order=["row_identity", "display_helper", "payload"],
        )


def test_outbound_role_order_missing_required_role_raises() -> None:
    frames = _frames_with_overrides_required()

    with pytest.raises(ValueError, match="permutation"):
        project_by_role(
            frames,
            frame="story_group_matrix_view",
            direction="outbound",
            helper_columns=["title"],
            key_columns=["story_id"],
            role_order=["row_identity", "matrix_value"],
        )


def test_outbound_with_empty_matrix_value_set_drops_no_columns() -> None:
    frames = {
        "matrix_view": pd.DataFrame(
            {"title": ["A"], "story_id": ["s1"]}
        ),
    }

    out = project_by_role(
        frames,
        frame="matrix_view",
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert list(out["matrix_view"].columns) == ["title", "story_id"]


def test_outbound_preserves_data_values_for_retained_columns() -> None:
    frames = _frames_with_overrides_required()

    out = project_by_role(
        frames,
        frame="story_group_matrix_view",
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert out["story_group_matrix_view"]["story_id"].tolist() == ["s1", "s2"]
    assert out["story_group_matrix_view"]["title"].tolist() == [
        "Alpha story",
        "Beta story",
    ]
    assert out["story_group_matrix_view"]["Alpha"].tolist() == ["E", ""]
    assert out["story_group_matrix_view"]["Beta"].tolist() == ["", "S"]


def test_outbound_does_not_drop_columns() -> None:
    frames = _frames_with_overrides_required()

    out = project_by_role(
        frames,
        frame="story_group_matrix_view",
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert set(out["story_group_matrix_view"].columns) == set(
        frames["story_group_matrix_view"].columns
    )


# ---------------------------------------------------------------------------
# Inbound semantics
# ---------------------------------------------------------------------------


def test_inbound_default_order_is_keys_then_matrix_values_and_drops_helpers() -> None:
    frames = _frames_with_overrides_required()

    out = project_by_role(
        frames,
        frame="story_group_matrix_view",
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert list(out["story_group_matrix_view"].columns) == [
        "story_id",
        "Alpha",
        "Beta",
    ]


def test_inbound_drops_display_helper_columns() -> None:
    frames = _frames_with_overrides_required()

    out = project_by_role(
        frames,
        frame="story_group_matrix_view",
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert "title" not in out["story_group_matrix_view"].columns


def test_inbound_role_order_with_display_helper_raises() -> None:
    frames = _frames_with_overrides_required()

    with pytest.raises(ValueError, match="display_helper"):
        project_by_role(
            frames,
            frame="story_group_matrix_view",
            direction="inbound",
            helper_columns=["title"],
            key_columns=["story_id"],
            role_order=["row_identity", "display_helper", "matrix_value"],
        )


def test_inbound_role_order_with_unknown_role_raises() -> None:
    frames = _frames_with_overrides_required()

    with pytest.raises(ValueError, match="unknown role"):
        project_by_role(
            frames,
            frame="story_group_matrix_view",
            direction="inbound",
            helper_columns=["title"],
            key_columns=["story_id"],
            role_order=["row_identity", "payload"],
        )


def test_inbound_preserves_data_values_for_retained_columns() -> None:
    frames = _frames_with_overrides_required()

    out = project_by_role(
        frames,
        frame="story_group_matrix_view",
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert out["story_group_matrix_view"]["story_id"].tolist() == ["s1", "s2"]
    assert out["story_group_matrix_view"]["Alpha"].tolist() == ["E", ""]
    assert out["story_group_matrix_view"]["Beta"].tolist() == ["", "S"]


def test_inbound_custom_role_order_matrix_value_first_respected() -> None:
    frames = _frames_with_overrides_required()

    out = project_by_role(
        frames,
        frame="story_group_matrix_view",
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
        role_order=["matrix_value", "row_identity"],
    )

    assert list(out["story_group_matrix_view"].columns) == [
        "Alpha",
        "Beta",
        "story_id",
    ]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_invalid_direction_raises_validation_error() -> None:
    frames = _frames_with_overrides_required()

    with pytest.raises(ValueError, match="outbound"):
        project_by_role(
            frames,
            frame="story_group_matrix_view",
            direction="sideways",
            helper_columns=["title"],
            key_columns=["story_id"],
        )


def test_none_direction_raises_validation_error() -> None:
    frames = _frames_with_overrides_required()

    with pytest.raises(ValueError, match="explicit"):
        project_by_role(
            frames,
            frame="story_group_matrix_view",
            direction=None,  # type: ignore[arg-type]
            helper_columns=["title"],
            key_columns=["story_id"],
        )


def test_missing_frame_raises_validation_error() -> None:
    frames = _frames_with_overrides_required()

    with pytest.raises(ValueError, match="non-empty"):
        project_by_role(
            frames,
            frame="",
            direction="outbound",
            helper_columns=["title"],
            key_columns=["story_id"],
        )


def test_unknown_frame_raises_clear_error() -> None:
    with pytest.raises(KeyError, match="not present"):
        project_by_role(
            {},
            frame="missing_view",
            direction="outbound",
            helper_columns=["title"],
            key_columns=["story_id"],
        )


# ---------------------------------------------------------------------------
# Roundtrip
# ---------------------------------------------------------------------------


def test_outbound_then_inbound_restores_retained_columns_to_inbound_default() -> None:
    frames = _frames_with_overrides_required()

    rendered = project_by_role(
        frames,
        frame="story_group_matrix_view",
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )
    reimported = project_by_role(
        rendered,
        frame="story_group_matrix_view",
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert list(reimported["story_group_matrix_view"].columns) == [
        "story_id",
        "Alpha",
        "Beta",
    ]
    assert reimported["story_group_matrix_view"]["story_id"].tolist() == ["s1", "s2"]
    assert reimported["story_group_matrix_view"]["Alpha"].tolist() == ["E", ""]
    assert reimported["story_group_matrix_view"]["Beta"].tolist() == ["", "S"]


def test_resolver_meta_sources_supply_roles_without_explicit_overrides() -> None:
    frames = {
        "story_group_matrix_view": _story_group_matrix_view(),
        "_meta": {
            "xref_crosstable": {
                "story_group_matrix": {
                    "matrix": "story_group_matrix_view",
                    "row_keys": ["story_id"],
                },
            },
            "workbook_view": {
                "sheets": [
                    {"frame": "story_group_matrix_view", "sheet": "story_groups", "order": 0},
                ],
            },
            "sheets": {
                "story_groups": {"helper_columns": ["title"]},
            },
        },
    }

    out = project_by_role(
        frames,
        frame="story_group_matrix_view",
        direction="outbound",
    )

    assert list(out["story_group_matrix_view"].columns) == [
        "title",
        "story_id",
        "Alpha",
        "Beta",
    ]
