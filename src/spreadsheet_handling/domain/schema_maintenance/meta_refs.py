from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .model import ReferenceRoot

FRAME_KEYS = frozenset(
    {
        "frame",
        "logical_frame",
        "output_frame",
        "relation_frame",
        "source_frame",
        "target_frame",
    }
)
COLUMN_KEYS = frozenset(
    {
        "column",
        "column_key",
        "discriminator",
        "fk_column",
        "source_column",
        "target_column",
        "target_field",
        "target_key",
        "value",
        "value_column",
    }
)
COLUMN_LIST_KEYS = frozenset(
    {
        "columns",
        "column_order",
        "editable_columns",
        "helper_columns",
        "key_columns",
        "original_column_order",
        "row_keys",
        "target_columns",
        "value_columns",
    }
)

SUPPORTED_ROOT_NAMES = frozenset(
    {
        "constraints",
        "helper_policies",
        "sheets",
        "workbook_view",
        # Dedicated feature-aware handler; not scanned by the generic
        # key-name convention (real XRef references only).
        "xref_crosstable",
    }
)
BLOCKED_ROOTS_BY_NAME = {
    "compact_multiaxis": ReferenceRoot.COMPACT_MULTIAXIS,
    "legend_blocks": ReferenceRoot.LEGEND_BLOCKS,
    "sparse_defaults": ReferenceRoot.SPARSE_DEFAULTS,
    "split_by_discriminator": ReferenceRoot.SPLIT_BY_DISCRIMINATOR,
}
OUT_OF_SCOPE_ROOT_NAMES = frozenset(
    {
        "_hidden",
        "auto_filter",
        # Legacy family: no producer or runtime consumer remains; tolerated
        # pass-through sediment whose stale references block nothing.
        "cell_codecs",
        "column_widths",
        "freeze_header",
        "header_fill_rgb",
        "helper_fill_rgb",
        "horizontal_alignments",
        "text_orientations",
        "vertical_alignments",
        "workbook_meta_blob",
    }
)


@dataclass(frozen=True)
class SheetResolution:
    frame: str | None
    ambiguous: bool = False


def reference_root_for_blocked_name(root_name: str) -> ReferenceRoot:
    return BLOCKED_ROOTS_BY_NAME.get(root_name, ReferenceRoot.UNKNOWN_PLUGIN)


def is_out_of_scope_root(root_name: str) -> bool:
    return root_name in OUT_OF_SCOPE_ROOT_NAMES or root_name.startswith("__")


def is_known_schema_maintenance_root(root_name: str) -> bool:
    return root_name in SUPPORTED_ROOT_NAMES or root_name in BLOCKED_ROOTS_BY_NAME


def build_sheet_resolver(meta: Mapping[str, Any], target_frame: str) -> dict[str, SheetResolution]:
    """Resolve visible sheet names to logical frames for reference maintenance.

    Frame-only resolution: a sheet denotes exactly the frame mapped to it via
    the ``frame`` key. Legacy derived keys such as ``canonical_frame`` are not
    resolution candidates; sheet-scoped column references belong to the frame
    actually rendered on that sheet.
    """
    resolver: dict[str, SheetResolution] = {target_frame: SheetResolution(frame=target_frame)}
    workbook_view = meta.get("workbook_view")
    if not isinstance(workbook_view, Mapping):
        return resolver

    collected: dict[str, set[str]] = {}
    _collect_sheet_candidates(
        collected,
        workbook_view.get("sheets"),
        ("sheet",),
        ("frame",),
    )
    _collect_sheet_candidates(
        collected,
        workbook_view.get("sheet_mappings"),
        ("sheet", "visible_sheet"),
        ("frame",),
    )

    for sheet, frames in collected.items():
        if len(frames) == 1:
            resolver[sheet] = SheetResolution(frame=next(iter(frames)))
        else:
            resolver[sheet] = SheetResolution(frame=None, ambiguous=True)
    return resolver


def _collect_sheet_candidates(
    collected: dict[str, set[str]],
    entries: Any,
    sheet_keys: tuple[str, ...],
    frame_keys: tuple[str, ...],
) -> None:
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        sheet = _first_string(entry, sheet_keys)
        frame = _first_string(entry, frame_keys)
        if sheet is None or frame is None:
            continue
        collected.setdefault(sheet, set()).add(frame)


def resolve_sheet(
    resolver: Mapping[str, SheetResolution],
    sheet_name: Any,
) -> SheetResolution:
    if not isinstance(sheet_name, str) or not sheet_name:
        return SheetResolution(frame=None, ambiguous=True)
    return resolver.get(sheet_name, SheetResolution(frame=None))


def contains_structured_reference(value: Any, target_frame: str, column: str) -> bool:
    if isinstance(value, Mapping):
        if _mapping_contains_reference(value, target_frame, column):
            return True
        return any(contains_structured_reference(child, target_frame, column) for child in value.values())
    if _is_sequence(value):
        return any(contains_structured_reference(child, target_frame, column) for child in value)
    return False


def _mapping_contains_reference(value: Mapping[str, Any], target_frame: str, column: str) -> bool:
    has_frame = any(str(value.get(key)) == target_frame for key in FRAME_KEYS if key in value)
    has_column = any(str(value.get(key)) == column for key in COLUMN_KEYS if key in value)
    has_column_list = any(_sequence_contains(value.get(key), column) for key in COLUMN_LIST_KEYS if key in value)
    return has_frame and (has_column or has_column_list)


def _sequence_contains(value: Any, expected: str) -> bool:
    if not _is_sequence(value):
        return False
    return any(item == expected for item in value)


def _first_string(entry: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))
