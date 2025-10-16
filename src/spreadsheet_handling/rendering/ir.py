# rendering/ir.py
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
    kind: Literal["list", "custom"]
    area: AreaRef
    source_range_name: Optional[str] = None  # for list
    formula: Optional[str] = None           # for custom
    allow_empty: bool = True

@dataclass
class StyleSpec:
    name: str
    apply_to: AreaRef

@dataclass
class TableBlock:
    # Bindet EINEN DataFrame an eine Position im Sheet
    frame_name: str                 # Key im Frames-Dict
    top_left: CellRef               # Startzelle (inkl. Header)
    header_rows: int = 1
    header_cols: int = 1
    col_levels: int = 1
    row_levels: int = 0
    named_range: Optional[str] = None       # z.B. "Products"
    notes: Optional[str] = None             # Kommentar/Hinweis

@dataclass
class SheetIR:
    name: str
    tables: List[TableBlock] = field(default_factory=list)
    named_ranges: List[NamedRange] = field(default_factory=list)
    merges: List[AreaRef] = field(default_factory=list)
    validations: List[DataValidationSpec] = field(default_factory=list)
    styles: List[StyleSpec] = field(default_factory=list)
    meta: Dict = field(default_factory=dict)   # persistentes _meta (axes/grid etc.)

@dataclass
class WorkbookIR:
    sheets: Dict[str, SheetIR] = field(default_factory=dict)
    hidden_sheets: Dict[str, SheetIR] = field(default_factory=dict)  # z.B. _meta, _valid
