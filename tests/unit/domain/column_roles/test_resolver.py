from __future__ import annotations

import logging

import pandas as pd
import pytest

from spreadsheet_handling.domain.column_roles import (
    ROLE_DISPLAY_HELPER,
    ROLE_MATRIX_VALUE,
    ROLE_ROW_IDENTITY,
    UnknownRoleError,
    resolve_column_roles,
)


pytestmark = [
    pytest.mark.ftr("FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5"),
    pytest.mark.ftr("FTR-PROJECTED-FRAME-COLUMN-SEMANTICS-P5"),
]


def _matrix_view_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "title": ["A", "B"],
            "story_id": ["s1", "s2"],
            "Alpha": ["x", ""],
            "Beta": ["", "y"],
        }
    )


def test_resolves_row_identity_from_contract_xref_row_keys() -> None:
    frames = {
        "story_group_matrix_view": _matrix_view_frame(),
        "_meta": {
            "xref_crosstable": {
                "story_group_matrix": {
                    "matrix": "story_group_matrix_view",
                    "row_keys": ["story_id"],
                },
            },
        },
    }

    roles = resolve_column_roles(frames, frame="story_group_matrix_view")

    assert roles.row_identity == ["story_id"]


def test_explicit_key_columns_override_wins_over_meta() -> None:
    frames = {
        "story_group_matrix_view": _matrix_view_frame(),
        "_meta": {
            "xref_crosstable": {
                "story_group_matrix": {
                    "matrix": "story_group_matrix_view",
                    "row_keys": ["story_id"],
                },
            },
        },
    }

    roles = resolve_column_roles(
        frames,
        frame="story_group_matrix_view",
        key_columns=["title"],
    )

    assert roles.row_identity == ["title"]


def test_resolves_display_helper_from_workbook_view_helper_columns() -> None:
    frames = {
        "story_group_matrix_view": _matrix_view_frame(),
        "_meta": {
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

    roles = resolve_column_roles(frames, frame="story_group_matrix_view")

    assert roles.display_helper == ["title"]


def test_resolves_display_helper_from_fk_helper_provenance() -> None:
    frame = pd.DataFrame(
        {
            "id": ["p1"],
            "name": ["alpha"],
            "_regions_name": ["north"],
            "Alpha": ["x"],
        }
    )
    frames = {
        "places": frame,
        "_meta": {
            "derived": {
                "sheets": {
                    "places": {
                        "helper_columns": [
                            {
                                "column": "_regions_name",
                                "fk_column": "region_id",
                                "target": "regions",
                                "target_key": "id",
                                "value_field": "name",
                            },
                        ],
                    },
                },
            },
        },
    }

    roles = resolve_column_roles(frames, frame="places")

    assert roles.display_helper == ["_regions_name"]


def test_display_helper_unions_view_and_fk_helper_sources_without_duplicates() -> None:
    frame = pd.DataFrame(
        {
            "title": ["A"],
            "_regions_name": ["north"],
            "story_id": ["s1"],
            "Alpha": ["x"],
        }
    )
    frames = {
        "places_matrix_view": frame,
        "_meta": {
            "workbook_view": {
                "sheets": [
                    {"frame": "places_matrix_view", "sheet": "places_matrix_view", "order": 0},
                ],
            },
            "sheets": {
                "places_matrix_view": {"helper_columns": ["title", "_regions_name"]},
            },
            "derived": {
                "sheets": {
                    "places_matrix_view": {
                        "helper_columns": [
                            {"column": "_regions_name", "fk_column": "region_id"},
                        ],
                    },
                },
            },
        },
    }

    roles = resolve_column_roles(frames, frame="places_matrix_view")

    assert roles.display_helper == ["title", "_regions_name"]


def test_explicit_helper_columns_override_wins_over_meta_sources() -> None:
    frames = {
        "story_group_matrix_view": _matrix_view_frame(),
        "_meta": {
            "workbook_view": {
                "sheets": [
                    {"frame": "story_group_matrix_view", "sheet": "story_groups", "order": 0},
                ],
            },
            "sheets": {
                "story_groups": {"helper_columns": ["Alpha"]},
            },
        },
    }

    roles = resolve_column_roles(
        frames,
        frame="story_group_matrix_view",
        helper_columns=["title"],
    )

    assert roles.display_helper == ["title"]


def test_matrix_value_is_rest_by_exclusion_within_the_frame() -> None:
    frames = {
        "story_group_matrix_view": _matrix_view_frame(),
    }

    roles = resolve_column_roles(
        frames,
        frame="story_group_matrix_view",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert roles.matrix_value == ["Alpha", "Beta"]


def test_warn_only_on_missing_row_identity(caplog: pytest.LogCaptureFixture) -> None:
    frames = {
        "matrix_view": _matrix_view_frame(),
    }

    with caplog.at_level(logging.WARNING, logger="sheets.column_roles"):
        roles = resolve_column_roles(frames, frame="matrix_view")

    assert roles.row_identity == []
    assert roles.matrix_value == ["title", "story_id", "Alpha", "Beta"]
    assert any("row_identity" in record.message for record in caplog.records)


def test_frame_not_in_pipeline_state_raises_clear_error() -> None:
    with pytest.raises(KeyError, match="not present"):
        resolve_column_roles({}, frame="missing_view")


def test_columns_for_returns_role_specific_lists() -> None:
    frames = {
        "story_group_matrix_view": _matrix_view_frame(),
    }
    roles = resolve_column_roles(
        frames,
        frame="story_group_matrix_view",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert roles.columns_for(ROLE_DISPLAY_HELPER) == ["title"]
    assert roles.columns_for(ROLE_ROW_IDENTITY) == ["story_id"]
    assert roles.columns_for(ROLE_MATRIX_VALUE) == ["Alpha", "Beta"]
    with pytest.raises(UnknownRoleError):
        roles.columns_for("payload")


def test_within_role_order_follows_input_column_order_not_override_order() -> None:
    frame = pd.DataFrame(
        {
            "first_helper": ["a"],
            "story_id": ["s1"],
            "second_helper": ["b"],
            "Alpha": ["x"],
        }
    )
    frames = {"matrix_view": frame}

    roles = resolve_column_roles(
        frames,
        frame="matrix_view",
        helper_columns=["second_helper", "first_helper"],
        key_columns=["story_id"],
    )

    assert roles.display_helper == ["first_helper", "second_helper"]


def test_overlap_between_identity_and_helper_resolves_to_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame = pd.DataFrame({"story_id": ["s1"], "Alpha": ["x"]})
    frames = {"matrix_view": frame}

    with caplog.at_level(logging.WARNING, logger="sheets.column_roles"):
        roles = resolve_column_roles(
            frames,
            frame="matrix_view",
            helper_columns=["story_id"],
            key_columns=["story_id"],
        )

    assert roles.row_identity == ["story_id"]
    assert roles.display_helper == []
    assert any(
        "both row_identity and display_helper" in record.message for record in caplog.records
    )


# ---------------------------------------------------------------------------
# FTR-XREF-CROSSTABLE Slice A -- A2: XRef-meta row-identity path
# ---------------------------------------------------------------------------


@pytest.mark.ftr("FTR-XREF-CROSSTABLE")
class TestXrefMetaRowIdentityPath:
    """Characterize the resolver's XRef-meta row-identity derivation path.

    Locks the interim resolver behavior: when _meta.xref_crosstable[*].matrix
    matches the requested frame name, the stored row_keys supply row_identity
    without an explicit key_columns override.  Guards the behavior before Slice D.
    """

    @staticmethod
    def _cast_frame() -> pd.DataFrame:
        return pd.DataFrame({
            "story_id": ["s1"],
            "story_title": ["The Cave"],
            "Galli": ["E"],
            "Donzo": ["N"],
        })

    def test_xref_meta_row_keys_become_row_identity(self) -> None:
        frames = {
            "story_cast_role_matrix": self._cast_frame(),
            "_meta": {
                "xref_crosstable": {
                    "story_cast_role_matrix": {
                        "matrix": "story_cast_role_matrix",
                        "row_keys": ["story_id"],
                    },
                },
            },
        }

        roles = resolve_column_roles(frames, frame="story_cast_role_matrix")

        assert roles.row_identity == ["story_id"]

    def test_non_identity_columns_become_matrix_value_by_exclusion(self) -> None:
        frames = {
            "story_cast_role_matrix": self._cast_frame(),
            "_meta": {
                "xref_crosstable": {
                    "story_cast_role_matrix": {
                        "matrix": "story_cast_role_matrix",
                        "row_keys": ["story_id"],
                    },
                },
            },
        }

        roles = resolve_column_roles(frames, frame="story_cast_role_matrix")

        assert "story_id" not in roles.matrix_value
        assert "story_title" in roles.matrix_value
        assert "Galli" in roles.matrix_value
        assert "Donzo" in roles.matrix_value

    def test_xref_meta_for_different_frame_does_not_supply_row_identity(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        frames = {
            "product_matrix": self._cast_frame(),
            "_meta": {
                "xref_crosstable": {
                    "story_cast_role_matrix": {
                        "matrix": "story_cast_role_matrix",
                        "row_keys": ["story_id"],
                    },
                },
            },
        }

        with caplog.at_level(logging.WARNING, logger="sheets.column_roles"):
            roles = resolve_column_roles(frames, frame="product_matrix")

        assert roles.row_identity == []
        assert any("row_identity" in record.message for record in caplog.records)

    def test_display_helper_from_view_config_independent_of_xref_row_identity(
        self,
    ) -> None:
        frames = {
            "story_cast_role_matrix": self._cast_frame(),
            "_meta": {
                "xref_crosstable": {
                    "story_cast_role_matrix": {
                        "matrix": "story_cast_role_matrix",
                        "row_keys": ["story_id"],
                    },
                },
                "workbook_view": {
                    "sheets": [
                        {
                            "frame": "story_cast_role_matrix",
                            "sheet": "story_cast_role",
                            "order": 0,
                        },
                    ],
                },
                "sheets": {
                    "story_cast_role": {"helper_columns": ["story_title"]},
                },
            },
        }

        roles = resolve_column_roles(frames, frame="story_cast_role_matrix")

        assert roles.row_identity == ["story_id"]
        assert roles.display_helper == ["story_title"]
        assert roles.matrix_value == ["Galli", "Donzo"]


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
def test_ambiguous_xref_matrix_entries_fail_row_identity_resolution() -> None:
    # Consistent family policy: multiple XRef entries claiming the same
    # matrix frame must not be resolved by insertion order.
    frames = {
        "story_group_matrix_view": _matrix_view_frame(),
        "_meta": {
            "xref_crosstable": {
                "first": {
                    "matrix": "story_group_matrix_view",
                    "row_keys": ["story_id"],
                },
                "second": {
                    "matrix": "story_group_matrix_view",
                    "row_keys": ["title"],
                },
            },
        },
    }

    with pytest.raises(ValueError, match="Ambiguous xref_crosstable metadata"):
        resolve_column_roles(frames, frame="story_group_matrix_view")


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
def test_explicit_key_columns_override_bypasses_ambiguous_xref_entries() -> None:
    frames = {
        "story_group_matrix_view": _matrix_view_frame(),
        "_meta": {
            "xref_crosstable": {
                "first": {
                    "matrix": "story_group_matrix_view",
                    "row_keys": ["story_id"],
                },
                "second": {
                    "matrix": "story_group_matrix_view",
                    "row_keys": ["title"],
                },
            },
        },
    }

    roles = resolve_column_roles(
        frames,
        frame="story_group_matrix_view",
        key_columns=["story_id"],
    )

    assert roles.row_identity == ["story_id"]
