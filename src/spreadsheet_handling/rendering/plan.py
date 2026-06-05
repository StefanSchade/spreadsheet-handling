from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Union, Iterable

from spreadsheet_handling.core.formulas import FormulaSpec

# ----- Render Operations -----

@dataclass(frozen=True)
class DefineSheet:
    sheet: str
    order: int

@dataclass(frozen=True)
class SetHeader:
    sheet: str
    row: int
    col: int
    text: str


@dataclass(frozen=True)
class MergeCells:
    sheet: str
    r1: int
    c1: int
    r2: int
    c2: int

@dataclass(frozen=True)
class ApplyHeaderStyle:
    sheet: str
    row: int
    col: int
    bold: bool = False
    fill_rgb: Optional[str] = None  # "#RRGGBB" or None

@dataclass(frozen=True)
class SetAutoFilter:
    sheet: str
    r1: int
    c1: int
    r2: int
    c2: int

@dataclass(frozen=True)
class SetFreeze:
    sheet: str
    row: int
    col: int

@dataclass(frozen=True)
class SetColumnWidth:
    sheet: str
    col: int
    width: float

@dataclass(frozen=True)
class AddValidation:
    sheet: str
    kind: str  # spreadsheet-neutral validation kind, e.g. "list"
    r1: int
    c1: int
    r2: int
    c2: int
    formula: FormulaSpec  # backend-neutral validation intent
    allow_empty: bool = True

@dataclass(frozen=True)
class ApplyColumnStyle:
    """Apply a fill color to an entire data column (below header)."""
    sheet: str
    col: int          # 1-based column index
    from_row: int     # typically 2 (first data row)
    to_row: int       # last data row
    fill_rgb: Optional[str] = None  # "#RRGGBB" or None

@dataclass(frozen=True)
class WriteDataBlock:
    """Write a rectangular block of cell values."""
    sheet: str
    r1: int       # top-left row (1-based)
    c1: int       # top-left col (1-based)
    data: tuple   # tuple of tuples — row-major 2D data

@dataclass(frozen=True)
class WriteMeta:
    """Persist hidden workbook metadata payload in a backend-specific carrier."""

    sheet: str  # Current backends may use a hidden "_meta" sheet; other carriers remain possible.
    kv: Dict[str, str]  # concrete persisted representation of canonical workbook metadata
    hidden: bool = True

@dataclass(frozen=True)
class DefineNamedRange:
    name: str
    sheet: str
    r1: int
    c1: int
    r2: int
    c2: int


@dataclass(frozen=True)
class SetSheetProtection:
    """Enable sheet protection so locked cells cannot be edited."""
    sheet: str
    password: Optional[str] = None


@dataclass(frozen=True)
class ApplyCellLock:
    """Set the locked/unlocked state for a column range of cells."""
    sheet: str
    col: int          # 1-based column index
    from_row: int     # first row (header or data)
    to_row: int       # last row
    locked: bool = True


@dataclass(frozen=True)
class SetTextOrientation:
    """Apply a text rotation angle to a specific cell (row/col 1-based).

    ``rotation`` follows the XLSX textRotation convention:
      0   = horizontal (default)
      1–90  = counter-clockwise degrees
      91–180 = clockwise degrees (stored as 90 + CW_angle)
    """
    sheet: str
    row: int
    col: int
    rotation: int


_CANONICAL_HORIZONTAL_ALIGNMENTS: frozenset[str] = frozenset(
    {"left", "center", "right"}
)


_CANONICAL_VERTICAL_ALIGNMENTS: frozenset[str] = frozenset(
    {"top", "center", "bottom"}
)


@dataclass(frozen=True)
class SetHorizontalAlignment:
    """Apply a horizontal text alignment to a specific cell (row/col 1-based).

    ``horizontal`` is the project canonical encoding (XLSX-shaped) and is
    restricted to ``"left"``, ``"center"``, or ``"right"`` in this slice.
    Backend adapters convert to their carrier vocabulary on write.

    The vocabulary is enforced at construction so that direct ``RenderPlan``
    construction cannot bypass the canonical filter applied by the
    ``rendering.flow`` builder. Out-of-slice values
    (``general`` / ``fill`` / ``justify`` / ``distributed`` /
    ``centerContinuous``) raise ``ValueError`` here rather than reaching a
    backend renderer that would either drop them silently or emit a value
    the receiving carrier cannot interpret.
    """
    sheet: str
    row: int
    col: int
    horizontal: str

    def __post_init__(self) -> None:
        if self.horizontal not in _CANONICAL_HORIZONTAL_ALIGNMENTS:
            raise ValueError(
                "SetHorizontalAlignment.horizontal must be one of "
                f"{sorted(_CANONICAL_HORIZONTAL_ALIGNMENTS)!r}; "
                f"got {self.horizontal!r}"
            )


@dataclass(frozen=True)
class SetVerticalAlignment:
    """Apply a vertical text alignment to a specific cell (row/col 1-based).

    ``vertical`` is the project canonical encoding (XLSX-shaped) and is
    restricted to ``"top"``, ``"center"``, or ``"bottom"`` in this slice.
    Backend adapters convert to their carrier vocabulary on write; ODS
    emits ``style:vertical-align="middle"`` for canonical ``"center"``.

    The vocabulary is enforced at construction so that direct ``RenderPlan``
    construction cannot bypass the canonical filter applied by the
    ``rendering.flow`` builder. Out-of-slice values
    (``justify`` / ``distributed`` from XLSX, ``automatic`` from ODS,
    ``middle`` as the unnormalized ODS form) raise ``ValueError`` here
    rather than reaching a backend renderer that would either drop them
    silently or emit a value the receiving carrier cannot interpret.
    """
    sheet: str
    row: int
    col: int
    vertical: str

    def __post_init__(self) -> None:
        if self.vertical not in _CANONICAL_VERTICAL_ALIGNMENTS:
            raise ValueError(
                "SetVerticalAlignment.vertical must be one of "
                f"{sorted(_CANONICAL_VERTICAL_ALIGNMENTS)!r}; "
                f"got {self.vertical!r}"
            )


RenderOp = Union[
    DefineSheet,
    SetHeader,
    MergeCells,
    ApplyHeaderStyle,
    ApplyColumnStyle,
    SetAutoFilter,
    SetFreeze,
    SetColumnWidth,
    SetTextOrientation,
    SetHorizontalAlignment,
    SetVerticalAlignment,
    AddValidation,
    WriteDataBlock,
    WriteMeta,
    DefineNamedRange,
    SetSheetProtection,
    ApplyCellLock,
]

# ----- Render Plan -----

@dataclass
class RenderPlan:
    ops: List[RenderOp] = field(default_factory=list)
    sheet_order: List[str] = field(default_factory=list)

    def add(self, op: RenderOp) -> None:
        self.ops.append(op)
        if isinstance(op, DefineSheet):
            self.sheet_order.append(op.sheet)

    def extend(self, ops: Iterable[RenderOp]) -> None:
        for op in ops:
            self.add(op)
