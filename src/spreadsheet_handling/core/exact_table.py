"""Backend-neutral exact-table carrier (GX-3b).

GX-3b of ``FTR-XREF-AXIS-MAPPINGS-P4A2`` (merged grouped-XRef capability). A
small, leaf-only value that carries a parsed exact table across the
generic-to-domain boundary: the lossless per-cell ``header_grid`` (GX-3a),
the row-major data cells, and the table geometry.

It is the single exchanged exact-table value in both directions:

* the reverse path -- ``rendering.workbook_projection.workbookir_to_frames``
  publishes one per exact-mode sheet, and the grouped-domain
  ``reconstruct_grouped_matrix`` step interprets it;
* the forward path -- ``grouped_matrix_to_exact_table`` returns one, which the
  workbook composer projects into an exact ``TableBlock``.

Living in ``core`` keeps it importable by both ``rendering`` (producer) and
``domain`` (consumer) without violating the layer guards: ``domain`` may not
import ``rendering``, and ``core`` stays leaf. The carrier holds only built-in
strings, tuples, and ints (``data`` cells stay whatever the parser produced);
no pandas, rendering, or domain type enters it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class ExactTable:
    """A parsed exact table: lossless header grid, data cells, and geometry.

    ``header_grid`` is ``tuple[tuple[str, ...], ...]`` (top -> leaf, verbatim,
    blanks kept as ``""``), ``data`` is row-major ``tuple[tuple[Any, ...], ...]``.
    ``header_rows`` equals ``len(header_grid)`` and ``n_cols`` the physical
    column count; both are stored explicitly so consumers need not re-measure.
    """

    header_grid: tuple[tuple[str, ...], ...]
    data: tuple[tuple[Any, ...], ...]
    header_rows: int
    n_cols: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "header_grid", _rows_of_str(self.header_grid))
        object.__setattr__(self, "data", _rows_of_any(self.data))


def _rows_of_str(rows: Sequence[Sequence[Any]]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple("" if cell is None else str(cell) for cell in row) for row in rows)


def _rows_of_any(rows: Sequence[Sequence[Any]]) -> tuple[tuple[Any, ...], ...]:
    return tuple(tuple(row) for row in rows)


__all__ = ["ExactTable"]
