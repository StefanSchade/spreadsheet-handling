from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Union, Iterable

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
class AddValidation:
    sheet: str
    kind: str  # spreadsheet-neutral validation kind, e.g. "list"
    r1: int
    c1: int
    r2: int
    c2: int
    formula: str  # adapter-facing validation expression derived from meta_canonical["constraints"]
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

RenderOp = Union[
    DefineSheet,
    SetHeader,
    MergeCells,
    ApplyHeaderStyle,
    ApplyColumnStyle,
    SetAutoFilter,
    SetFreeze,
    AddValidation,
    WriteDataBlock,
    WriteMeta,
    DefineNamedRange,
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
