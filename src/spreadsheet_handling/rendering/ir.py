from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Literal

CellRef = Tuple[int, int]           # (row, col) 1-based
AreaRef = Tuple[int, int, int, int] # (r1, c1, r2, c2)

@dataclass
class NamedRange:
    name: str
    sheet: str
    area: AreaRef

@dataclass
class DataValidationSpec:
    kind: str                          # e.g., "list"
    area: Tuple[int, int, int, int]    # (r1, c1, r2, c2), 1-based
    formula: str                       # e.g., '"A,B,C"'
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
    # legacy alias (to be removed under FTR-IR-TYPING-CANONICAL)
    top_left: Optional[tuple[int, int]] = None

    def __post_init__(self):
        if self.top_left is not None:
            # only apply if caller didn’t set canonical fields
            if (self.top, self.left) == (1, 1):
                self.top, self.left = self.top_left
            # optionally warn:
            # warnings.warn("TableBlock.top_left is deprecated; use top/left", DeprecationWarning)


@dataclass
class SheetIR:
    name: str
    tables: List[TableBlock] = field(default_factory=list)
    validations: List[DataValidationSpec] = field(default_factory=list)
    meta: Dict[str, object] = field(default_factory=dict)
    styles: List[StyleSpec] = field(default_factory=list)

@dataclass
class WorkbookIR:
    sheets: Dict[str, SheetIR] = field(default_factory=dict)
    hidden_sheets: Dict[str, SheetIR] = field(default_factory=dict)
