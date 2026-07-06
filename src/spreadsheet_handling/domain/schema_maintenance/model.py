from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


Frames = dict[str, Any]


class SchemaOperationKind(Enum):
    ADD_COLUMN = "add_column"
    DROP_COLUMN = "drop_column"
    RENAME_COLUMN = "rename_column"
    REORDER_COLUMNS = "reorder_columns"


class WriteIntent(Enum):
    DRY_RUN = "dry_run"
    WRITE = "write"


class ReferenceAction(Enum):
    UPDATED = "updated"
    PRUNED = "pruned"
    BLOCKED = "blocked"
    UNAFFECTED = "unaffected"
    DROPPED_DERIVED = "dropped_derived"
    IGNORED_DERIVED = "ignored_derived"


class ReferenceRoot(Enum):
    CONSTRAINTS = "constraints"
    HELPER_POLICIES_FK = "helper_policies.fk"
    HELPER_POLICIES_LOOKUP = "helper_policies.lookup"
    SHEETS = "sheets"
    WORKBOOK_VIEW = "workbook_view"
    FRAME_LIFECYCLE = "frame_lifecycle"
    XREF_CROSSTABLE = "xref_crosstable"
    SPLIT_BY_DISCRIMINATOR = "split_by_discriminator"
    COMPACT_MULTIAXIS = "compact_multiaxis"
    CELL_CODECS = "cell_codecs"
    SPARSE_DEFAULTS = "sparse_defaults"
    LEGEND_BLOCKS = "legend_blocks"
    DERIVED = "derived"
    UNKNOWN_PLUGIN = "unknown_plugin"


@dataclass(frozen=True)
class ColumnPlacement:
    mode: Literal["append", "before", "after"] = "append"
    column: str | None = None


@dataclass(frozen=True)
class ReorderSpec:
    mode: Literal["complete", "listed_first", "listed_last"]
    columns: tuple[str, ...]


@dataclass(frozen=True)
class SchemaMaintenanceRequest:
    kind: SchemaOperationKind
    target_frame: str
    source_column: str | None = None
    target_column: str | None = None
    default_value: Any = ""
    placement: ColumnPlacement | None = None
    reorder: ReorderSpec | None = None
    prune: bool = False
    write_intent: WriteIntent = WriteIntent.DRY_RUN


@dataclass(frozen=True)
class FrameChange:
    frame: str
    kind: SchemaOperationKind
    source_column: str | None
    target_column: str | None
    detail: str


@dataclass(frozen=True)
class MetadataReferenceChange:
    root: ReferenceRoot
    path: str
    action: ReferenceAction
    frame: str | None
    column: str | None
    detail: str


@dataclass(frozen=True)
class SchemaMaintenanceFailure:
    code: str
    message: str
    frame: str | None = None
    column: str | None = None
    meta_path: str | None = None


@dataclass(frozen=True)
class SchemaMaintenanceWarning:
    code: str
    message: str
    frame: str | None = None
    column: str | None = None
    meta_path: str | None = None


@dataclass(frozen=True)
class SchemaMaintenanceReport:
    operation: SchemaMaintenanceRequest
    frame_changes: tuple[FrameChange, ...] = field(default_factory=tuple)
    metadata_changes: tuple[MetadataReferenceChange, ...] = field(default_factory=tuple)
    failures: tuple[SchemaMaintenanceFailure, ...] = field(default_factory=tuple)
    warnings: tuple[SchemaMaintenanceWarning, ...] = field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        return bool(self.failures)


@dataclass(frozen=True)
class SchemaMaintenanceResult:
    frames: Frames
    report: SchemaMaintenanceReport
