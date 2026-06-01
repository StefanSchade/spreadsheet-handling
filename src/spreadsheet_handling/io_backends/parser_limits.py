"""Shared dimension bounds for spreadsheet backend parsers.

Pathological inputs (e.g. an ODS workbook whose cells carry sheet-wide
``number-columns-repeated`` / ``number-rows-repeated`` formatting fillers) can
trigger uncontrolled allocation if a parser materializes every implied cell
position. These limits act as a defense-in-depth: parsers should still avoid
materializing empty repeated cells, but if a workbook genuinely declares more
rows / columns / cells than configured, the parser fails fast with a typed
error instead of exhausting memory.

The defaults align with the theoretical maxima of Excel / LibreOffice Calc
(1,048,576 rows × 16,384 columns) for the per-axis bounds, and a generous
per-sheet cell budget that comfortably covers realistic data while bounding
worst-case allocation.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_ROWS = 1_048_576
DEFAULT_MAX_COLS = 16_384
DEFAULT_MAX_CELLS = 10_000_000


class SpreadsheetTooLargeError(ValueError):
    """Raised when a parsed sheet exceeds configured dimension bounds."""


@dataclass(frozen=True)
class ParserLimits:
    max_rows: int = DEFAULT_MAX_ROWS
    max_cols: int = DEFAULT_MAX_COLS
    max_cells: int = DEFAULT_MAX_CELLS

    def enforce(
        self,
        *,
        context: str,
        rows: int = 0,
        cols: int = 0,
        cells: int = 0,
    ) -> None:
        if rows > self.max_rows:
            raise SpreadsheetTooLargeError(
                f"{context}: row count {rows} exceeds limit {self.max_rows}. "
                "Inspect the input for sheet-wide formatting fillers or relax "
                "limits via parser configuration."
            )
        if cols > self.max_cols:
            raise SpreadsheetTooLargeError(
                f"{context}: column count {cols} exceeds limit {self.max_cols}. "
                "Inspect the input for sheet-wide formatting fillers or relax "
                "limits via parser configuration."
            )
        if cells > self.max_cells:
            raise SpreadsheetTooLargeError(
                f"{context}: materialized cell count {cells} exceeds limit "
                f"{self.max_cells}. Inspect the input for sheet-wide formatting "
                "fillers or relax limits via parser configuration."
            )


DEFAULT_LIMITS = ParserLimits()


__all__ = [
    "DEFAULT_LIMITS",
    "DEFAULT_MAX_CELLS",
    "DEFAULT_MAX_COLS",
    "DEFAULT_MAX_ROWS",
    "ParserLimits",
    "SpreadsheetTooLargeError",
]
