"""Migration-parity tests for FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5.

Covers the five outbound and five inbound dino_insel projection surfaces
enumerated in the FTR's *Current call-site inventory*. The tests assert
that `project_by_role` produces the same retained column set, column
order, and frame name that the pre-migration plugins produced on the
same fixture shape, and that the inbound flow continues to interoperate
with `expand_xref drop_empty: true` / `expand_compact_multiaxis
drop_empty: true` end-to-end.

The fixtures match the worldbuilding shape (`story_id` row identity,
`title` display helper, dynamic per-cast / per-group matrix columns).
They are deliberately not loaded from the worldbuilding repo so that
core can be validated in isolation.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.compact_multiaxis import (
    expand_compact_multiaxis,
)
from spreadsheet_handling.domain.transformations.project_by_role import (
    project_by_role,
)
from spreadsheet_handling.domain.transformations.xref_crosstable import expand_xref


pytestmark = pytest.mark.ftr("FTR-DYNAMIC-FRAME-PROJECTION-IMPL-P5")


OUTBOUND_SURFACES: tuple[str, ...] = (
    "story_group_matrix_view",
    "story_cast_role_matrix_view",
    "story_cast_notes_matrix_view",
    "story_cast_character_development_matrix_view",
    "story_cast_crystal_matrix_view",
)

# Inbound projects in place on the same `*_matrix_view` frame names; the
# pre-migration `*_matrix_payload` intermediate is retired by the
# upstream-rename strategy and the downstream `expand_*` consumers read
# `*_matrix_view` directly.
INBOUND_SURFACES: tuple[str, ...] = OUTBOUND_SURFACES


def _outbound_matrix_view(matrix_value_columns: tuple[str, ...]) -> pd.DataFrame:
    """Build a fixture in the shape `join_frames` produces upstream.

    `contract_xref dense_axes.rows_from: { frame: stories, key: id }`
    guarantees deterministic row order keyed by `stories.id`. The
    fixture is pre-sorted by `story_id` to mirror that determinism.
    Column order follows the upstream `join_frames` shape: keys first,
    then matrix columns, then the joined-in `title` helper at the end.
    """
    rows: list[dict[str, Any]] = []
    for index, story_id in enumerate(("s1", "s2", "s3"), start=1):
        row: dict[str, Any] = {"story_id": story_id}
        for column in matrix_value_columns:
            row[column] = f"v{index}_{column}"
        row["title"] = f"Story {index}"
        rows.append(row)
    column_order = ["story_id", *matrix_value_columns, "title"]
    return pd.DataFrame(rows, columns=column_order)


def _outbound_columns_expected(matrix_value_columns: tuple[str, ...]) -> list[str]:
    return ["title", "story_id", *matrix_value_columns]


def _inbound_columns_expected(matrix_value_columns: tuple[str, ...]) -> list[str]:
    return ["story_id", *matrix_value_columns]


def _matrix_value_columns_for(surface: str) -> tuple[str, ...]:
    if surface == "story_group_matrix_view":
        return ("alpha_group", "beta_group", "gamma_group")
    return ("Alice", "Bob", "Carol")


# ---------------------------------------------------------------------------
# All-10-surfaces parity: outbound + inbound column shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface", OUTBOUND_SURFACES)
def test_outbound_column_shape_parity_per_surface(surface: str) -> None:
    matrix_value_columns = _matrix_value_columns_for(surface)
    frames: dict[str, Any] = {surface: _outbound_matrix_view(matrix_value_columns)}

    out = project_by_role(
        frames,
        frame=surface,
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert list(out[surface].columns) == _outbound_columns_expected(matrix_value_columns)
    # Frame-name parity: the in-place projection keeps the `*_matrix_view`
    # name that downstream `configure_workbook_view` entries consume.
    assert surface in out


@pytest.mark.parametrize("surface", INBOUND_SURFACES)
def test_inbound_column_shape_parity_per_surface(surface: str) -> None:
    matrix_value_columns = _matrix_value_columns_for(surface)
    rendered_frames: dict[str, Any] = {
        surface: project_by_role(
            {surface: _outbound_matrix_view(matrix_value_columns)},
            frame=surface,
            direction="outbound",
            helper_columns=["title"],
            key_columns=["story_id"],
        )[surface]
    }

    out = project_by_role(
        rendered_frames,
        frame=surface,
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert list(out[surface].columns) == _inbound_columns_expected(matrix_value_columns)
    assert "title" not in out[surface].columns
    # Frame-name parity: the inbound in-place projection keeps the
    # `*_matrix_view` name that downstream `expand_compact_multiaxis` /
    # `expand_xref` consumers read.
    assert surface in out


# ---------------------------------------------------------------------------
# Row-order parity (outbound only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface", OUTBOUND_SURFACES)
def test_outbound_row_order_parity_per_surface(surface: str) -> None:
    """`project_by_role` must not reorder rows.

    The pre-migration plugin called `result.sort_values(("story_id",),
    kind="mergesort")`. The FTR removes that sort and relies on upstream
    `contract_xref dense_axes.rows_from: { frame: stories, key: id }` to
    provide deterministic row order keyed by `stories.id`. This test
    confirms the upstream order survives `project_by_role` (so the
    removed plugin-side sort is genuinely redundant for ordered input).
    """
    matrix_value_columns = _matrix_value_columns_for(surface)
    upstream = _outbound_matrix_view(matrix_value_columns)
    pre_migration_order = sorted(
        upstream["story_id"].tolist(), key=str
    )  # plugin sort_by=("story_id",)
    assert upstream["story_id"].tolist() == pre_migration_order, (
        "test fixture must already be sorted by story_id to mirror the "
        "deterministic upstream contract_xref output"
    )

    out = project_by_role(
        {surface: upstream},
        frame=surface,
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    assert out[surface]["story_id"].tolist() == pre_migration_order


# ---------------------------------------------------------------------------
# Empty-cell parity through `drop_empty: true` downstream consumers
# ---------------------------------------------------------------------------


def test_inbound_empty_cell_parity_through_expand_compact_multiaxis() -> None:
    """`drop_empty: true` must treat NaN identically across the migration.

    The pre-migration `build_story_cast_matrix_payload` plugin normalized
    NaN to `""` via `result.where(pd.notnull(...), "")`.
    `project_by_role` performs no value transformation. The end-to-end
    contract is that `expand_compact_multiaxis drop_empty: true` drops
    both NaN and empty-string cells, so the reimported payload must be
    identical regardless of whether the matrix carries NaN or `""`.
    """
    matrix = pd.DataFrame(
        [
            {"story_id": "s1", "title": "Alpha story", "g1": "C1", "g2": np.nan},
            {"story_id": "s2", "title": "Beta story", "g1": np.nan, "g2": "C2"},
        ]
    )

    projected = project_by_role(
        {"story_group_matrix_view": matrix.copy()},
        frame="story_group_matrix_view",
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )
    out = expand_compact_multiaxis(
        projected,
        matrix="story_group_matrix_view",
        output="story_group_named",
        row_keys=["story_id"],
        column_key="group_name",
        code="code",
        value="value",
        mode="whole_cell_code",
        allowed_codes=["C1", "C2"],
        drop_empty=True,
        name="story_group_matrix",
    )

    nan_records = out["story_group_named"].to_dict(orient="records")

    # Parallel run with NaN replaced by "" (the pre-migration plugin's
    # output shape) must produce byte-identical reimported records.
    matrix_pre_migration = matrix.where(pd.notnull(matrix), "")
    projected_pre = project_by_role(
        {"story_group_matrix_view": matrix_pre_migration.copy()},
        frame="story_group_matrix_view",
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )
    out_pre = expand_compact_multiaxis(
        projected_pre,
        matrix="story_group_matrix_view",
        output="story_group_named",
        row_keys=["story_id"],
        column_key="group_name",
        code="code",
        value="value",
        mode="whole_cell_code",
        allowed_codes=["C1", "C2"],
        drop_empty=True,
        name="story_group_matrix_pre",
    )

    empty_records = out_pre["story_group_named"].to_dict(orient="records")
    assert nan_records == empty_records


@pytest.mark.parametrize(
    "surface",
    (
        "story_cast_role_matrix_view",
        "story_cast_notes_matrix_view",
        "story_cast_character_development_matrix_view",
        "story_cast_crystal_matrix_view",
    ),
)
def test_inbound_empty_cell_parity_through_expand_xref(surface: str) -> None:
    """`expand_xref drop_empty: true` parity for the four story-cast surfaces.

    Same NaN-vs-`""` contract as the compact-multiaxis case, applied to
    the four story-cast inbound surfaces consumed by `expand_xref`.
    """
    matrix_value_columns = ("Alice", "Bob", "Carol")
    matrix = pd.DataFrame(
        [
            {
                "story_id": "s1",
                "title": "Alpha story",
                "Alice": "role-a",
                "Bob": np.nan,
                "Carol": "role-c",
            },
            {
                "story_id": "s2",
                "title": "Beta story",
                "Alice": np.nan,
                "Bob": "role-b",
                "Carol": np.nan,
            },
        ]
    )

    projected = project_by_role(
        {surface: matrix.copy()},
        frame=surface,
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )
    out_nan = expand_xref(
        projected,
        matrix=surface,
        output=f"{surface}_named",
        row_keys=["story_id"],
        value_columns=list(matrix_value_columns),
        column_key="character_name",
        value="value",
        drop_empty=True,
        name=f"{surface}_parity",
    )

    matrix_pre = matrix.where(pd.notnull(matrix), "")
    projected_pre = project_by_role(
        {surface: matrix_pre.copy()},
        frame=surface,
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )
    out_empty = expand_xref(
        projected_pre,
        matrix=surface,
        output=f"{surface}_named",
        row_keys=["story_id"],
        value_columns=list(matrix_value_columns),
        column_key="character_name",
        value="value",
        drop_empty=True,
        name=f"{surface}_parity_pre",
    )

    assert out_nan[f"{surface}_named"].to_dict(orient="records") == out_empty[
        f"{surface}_named"
    ].to_dict(orient="records")


# ---------------------------------------------------------------------------
# Resolver-input availability at each migrated call site
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface", OUTBOUND_SURFACES)
def test_resolver_input_availability_outbound_per_surface(surface: str) -> None:
    """Explicit overrides must be honored at the outbound call site.

    The FTR records that `configure_workbook_view` runs *after* the
    outbound projection sites and `contract_xref` row_keys are declared
    on the upstream `*_matrix` frame, so the scattered resolver sources
    are not reachable for the projected surface. Each call site must
    pass `helper_columns: [title]` / `key_columns: [story_id]`
    explicitly, and the resolver must consume those overrides.
    """
    matrix_value_columns = _matrix_value_columns_for(surface)
    fixture = _outbound_matrix_view(matrix_value_columns)
    # No `_meta`: the scattered resolver sources are absent on purpose.
    frames = {surface: fixture}

    out = project_by_role(
        frames,
        frame=surface,
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    columns = list(out[surface].columns)
    assert columns[0] == "title", (
        "helper_columns override must be honored; title must land first "
        f"on outbound surface {surface!r}"
    )
    assert columns[1] == "story_id", (
        "key_columns override must be honored; story_id must follow the "
        f"helper on outbound surface {surface!r}"
    )
    assert columns[2:] == list(matrix_value_columns)


@pytest.mark.parametrize("surface", INBOUND_SURFACES)
def test_resolver_input_availability_inbound_per_surface(surface: str) -> None:
    """Explicit overrides must be honored at the inbound call site too."""
    matrix_value_columns = _matrix_value_columns_for(surface)
    rendered = project_by_role(
        {surface: _outbound_matrix_view(matrix_value_columns)},
        frame=surface,
        direction="outbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    # No `_meta`: same as the outbound site, the inbound site cannot
    # rely on scattered sources and must use the explicit overrides.
    out = project_by_role(
        {surface: rendered[surface]},
        frame=surface,
        direction="inbound",
        helper_columns=["title"],
        key_columns=["story_id"],
    )

    columns = list(out[surface].columns)
    assert columns[0] == "story_id"
    assert columns[1:] == list(matrix_value_columns)
    assert "title" not in columns
