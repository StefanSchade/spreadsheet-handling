"""Backend-neutral helpers for the GX-3a exact multi-row header grid.

An exact header grid is ``tuple[tuple[str, ...], ...]`` -- one inner tuple per
header row (top to leaf), each holding the verbatim displayed string of every
physical header cell in that row (blanks kept as ``""``). The grid is produced by
the format-specific parser (see ``io_backends/xlsx/parser_interpretation.py``) and
consumed by the render-plan writer; this module holds only pure, format-neutral
operations on it.

Deterministic blank forward-fill is offered here as an *explicitly parameterised*
helper rather than being applied inside the read path: a generic layer cannot tell
a merge-repeat blank from a declared single-level (row-key) blank without
column-role knowledge it must not own (GX-3a scope boundary). The caller (GX-3b)
supplies the columns to skip.
"""
from __future__ import annotations

HeaderGrid = tuple[tuple[str, ...], ...]


def forward_fill_header_grid(
    grid: HeaderGrid,
    *,
    skip_columns: frozenset[int] = frozenset(),
) -> HeaderGrid:
    """Forward-fill blank cells horizontally within each header row.

    For every header row, a blank cell (``""``) takes the nearest preceding
    non-blank value in that same row, modelling a repeated/merged upper-level
    group written as blanks. Columns in ``skip_columns`` are never filled and
    their blanks are preserved verbatim -- the caller declares which physical
    columns are single-level (for example row-key columns) so their intentionally
    blank upper cells are not mistaken for repeats.

    The grid is not mutated; a new grid is returned. A leading blank in a
    fillable column (no preceding value) stays blank.
    """
    filled: list[tuple[str, ...]] = []
    for row in grid:
        new_row: list[str] = []
        carry = ""
        for col, cell in enumerate(row):
            if col in skip_columns:
                new_row.append(cell)
                # A skipped column does not seed or extend a fill run.
                carry = ""
                continue
            if cell != "":
                carry = cell
                new_row.append(cell)
            else:
                new_row.append(carry)
        filled.append(tuple(new_row))
    return tuple(filled)


__all__ = ["HeaderGrid", "forward_fill_header_grid"]
