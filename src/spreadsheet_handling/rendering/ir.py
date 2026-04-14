from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Optional, Literal

CellRef = Tuple[int, int]           # (row, col) 1-based
AreaRef = Tuple[int, int, int, int] # (r1, c1, r2, c2)

@dataclass
class NamedRange:
    name: str
    sheet: str
    area: AreaRef

@dataclass
class DataValidationSpec:
    kind: str                          # spreadsheet-neutral validation kind, e.g. "list"
    area: Tuple[int, int, int, int]    # (r1, c1, r2, c2), 1-based
    formula: str                       # adapter-facing validation expression; canonical rule meaning stays in meta_canonical["constraints"]
    allow_empty: bool = True

@dataclass
class StyleSpec:
    name: str
    apply_to: AreaRef

@dataclass
class TableBlock:
    frame_name: str
    top: int = 1
    left: int = 1
    header_rows: int = 1
    header_cols: int = 1
    n_rows: int = 0
    n_cols: int = 0
    headers: List[str] = field(default_factory=list)
    header_map: Dict[str, int] = field(default_factory=dict)
    data: Optional[List[List]] = None  # row-major 2D data (None = not populated)



@dataclass
class SheetIR:
    name: str
    tables: List[TableBlock] = field(default_factory=list)
    validations: List[DataValidationSpec] = field(default_factory=list)
    named_ranges: List[NamedRange] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    styles: List[StyleSpec] = field(default_factory=list)

    def __post_init__(self):
        if self.meta is None:
            self.meta = {}

@dataclass
class WorkbookIR:
    sheets: Dict[str, SheetIR] = field(default_factory=dict)
    hidden_sheets: Dict[str, SheetIR] = field(default_factory=dict)
