from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Protocol, TypedDict
import pandas as pd

Frame  = pd.DataFrame
Frames = Dict[str, Frame]

Level = Literal["info", "warn", "error"]
Role  = Literal["key", "fk", "helper", "calc", "readonly"]

@dataclass
class Issue:
    level: Level
    code: str
    msg: str
    sheet: str | None = None
    row: int | None = None
    col: str | None = None

@dataclass
class ColumnMeta:
    role: Role | None = None
    note: str | None = None

@dataclass
class SheetMeta:
    columns: Dict[str, ColumnMeta] = field(default_factory=dict)
    auto_filter: bool | None = None
    freeze_header: bool | None = None

@dataclass
class MetaDict:
    sheets: Dict[str, SheetMeta] = field(default_factory=dict)

@dataclass
class Context:
    app: Any = None         # can be AppConfig
    run_id: str | None = None
    strict: bool = False
    stash: Dict[str, Any] = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)

@dataclass
class StepResult:
    frames: Frames
    issues: List[Issue] = field(default_factory=list)
    meta: MetaDict = field(default_factory=MetaDict)
    exports: Dict[str, Any] = field(default_factory=dict)
    continue_: bool = True

class Step(Protocol):
    def __call__(self, data: Dict[str, Any], ctx: Context) -> StepResult: ...
