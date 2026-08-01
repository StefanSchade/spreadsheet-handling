"""Unit tests for the GX-3a backend-neutral header-grid helper.

GX-3a of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. ``forward_fill_header_grid`` is the
explicitly parameterised deterministic blank forward-fill offered for GX-3b; it is
never applied inside the read path.
"""
from __future__ import annotations

import pytest

from spreadsheet_handling.rendering.header_grid import forward_fill_header_grid

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")


def test_forward_fill_repeats_dynamic_blanks_from_left() -> None:
    grid = (("Kredit", "", "", "Einlage"),)
    assert forward_fill_header_grid(grid) == (("Kredit", "Kredit", "Kredit", "Einlage"),)


def test_forward_fill_skips_declared_single_level_columns() -> None:
    # Column 0 is a row-key column: its blank upper cell must stay blank.
    grid = (("", "Kredit", "", "Gruppe"), ("row_id", "Ann", "Fix", "Leaf"))
    filled = forward_fill_header_grid(grid, skip_columns=frozenset({0}))
    assert filled[0] == ("", "Kredit", "Kredit", "Gruppe")
    assert filled[1] == ("row_id", "Ann", "Fix", "Leaf")


def test_forward_fill_does_not_carry_across_a_skipped_column() -> None:
    # A skipped (row-key) column between dynamic groups resets the fill run.
    grid = (("A", "", "rk", "", "B"),)
    assert forward_fill_header_grid(grid, skip_columns=frozenset({2})) == (
        ("A", "A", "rk", "", "B"),
    )


def test_forward_fill_leading_blank_stays_blank() -> None:
    assert forward_fill_header_grid((("", "A", ""),)) == (("", "A", "A"),)


def test_forward_fill_is_pure_and_returns_new_grid() -> None:
    grid = (("A", ""),)
    out = forward_fill_header_grid(grid)
    assert out == (("A", "A"),)
    assert grid == (("A", ""),)  # input unchanged
