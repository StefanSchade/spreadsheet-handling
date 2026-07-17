"""Best-effort structural diagnostics for runtime pipeline metadata."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

import pandas as pd

MetaPath: TypeAlias = tuple[str, ...]


@dataclass(frozen=True)
class MetaDiff:
    """Structured, value-free description of metadata path changes."""

    added: tuple[MetaPath, ...] = ()
    changed: tuple[MetaPath, ...] = ()
    removed: tuple[MetaPath, ...] = ()
    limited: bool = False

    @property
    def unchanged(self) -> bool:
        return not self.added and not self.changed and not self.removed and not self.limited


@dataclass(frozen=True, repr=False)
class MetaSnapshot:
    """Internal snapshot of the runtime ``_meta`` structure only."""

    root: _SnapshotNode
    limited: bool = False


@dataclass(frozen=True, repr=False, eq=False)
class _ScalarSnapshot:
    value_type: type[object]
    value: object


@dataclass(frozen=True, repr=False, eq=False)
class _OpaqueSnapshot:
    value: object


@dataclass(frozen=True, repr=False, eq=False)
class _SequenceSnapshot:
    value_type: type[object]
    items: tuple[_SnapshotNode, ...]


@dataclass(frozen=True, repr=False, eq=False)
class _SetSnapshot:
    value_type: type[object]
    items: tuple[_ScalarSnapshot, ...]


@dataclass(frozen=True, repr=False, eq=False)
class _UnsafeEntrySnapshot:
    key: object
    value: _SnapshotNode


@dataclass(frozen=True, repr=False, eq=False)
class _MappingSnapshot:
    items: tuple[tuple[str, _SnapshotNode], ...]
    unsafe_entries: tuple[_UnsafeEntrySnapshot, ...] = ()


_SnapshotNode: TypeAlias = (
    _ScalarSnapshot | _OpaqueSnapshot | _SequenceSnapshot | _SetSnapshot | _MappingSnapshot
)
_SAFE_SCALAR_TYPES = (type(None), bool, int, float, complex, str, bytes)


@dataclass
class _DiffBuilder:
    added: list[MetaPath] = field(default_factory=list)
    changed: list[MetaPath] = field(default_factory=list)
    removed: list[MetaPath] = field(default_factory=list)
    limited: bool = False


def snapshot_meta(frames: Mapping[str, object]) -> MetaSnapshot:
    """Capture only ``frames['_meta']`` using the bounded diagnostic model."""

    if "_meta" not in frames:
        return MetaSnapshot(root=_MappingSnapshot(items=()))

    root, limited = _snapshot_node(frames["_meta"], active_ids=set())
    return MetaSnapshot(root=root, limited=limited)


def diff_meta(before: MetaSnapshot, after: MetaSnapshot) -> MetaDiff:
    """Compare two metadata snapshots and return sorted structural paths."""

    builder = _DiffBuilder(limited=before.limited or after.limited)
    _diff_nodes(before.root, after.root, (), builder)
    return MetaDiff(
        added=_sorted_paths(builder.added),
        changed=_sorted_paths(builder.changed),
        removed=_sorted_paths(builder.removed),
        limited=builder.limited,
    )


def format_meta_diff(step_name: str, diff: MetaDiff) -> str:
    """Format a compact human-readable summary without metadata values."""

    lines = [f"<- step: {step_name}"]
    if diff.unchanged:
        lines.append("meta: unchanged")
        return "\n".join(lines)
    if not diff.added and not diff.changed and not diff.removed:
        lines.append("meta: diagnostic limited")
        return "\n".join(lines)

    lines.append("meta:")
    _append_paths(lines, "added", diff.added)
    _append_paths(lines, "changed", diff.changed)
    _append_paths(lines, "removed", diff.removed)
    if diff.limited:
        lines.append("  limitation: unsupported structure")
    return "\n".join(lines)


def _snapshot_node(value: object, active_ids: set[int]) -> tuple[_SnapshotNode, bool]:
    if type(value) in _SAFE_SCALAR_TYPES:
        return _ScalarSnapshot(type(value), value), False
    if isinstance(value, pd.DataFrame):
        return _OpaqueSnapshot(value), False
    if isinstance(value, Mapping):
        return _snapshot_mapping(value, active_ids)
    if type(value) in (list, tuple):
        return _snapshot_sequence(value, active_ids)
    if type(value) in (set, frozenset):
        return _snapshot_set(value), False
    return _OpaqueSnapshot(value), False


def _snapshot_mapping(
    value: Mapping[object, object], active_ids: set[int]
) -> tuple[_SnapshotNode, bool]:
    object_id = id(value)
    if object_id in active_ids:
        return _OpaqueSnapshot(value), True

    active_ids.add(object_id)
    items: list[tuple[str, _SnapshotNode]] = []
    unsafe_entries: list[_UnsafeEntrySnapshot] = []
    limited = False
    try:
        for key, child in value.items():
            child_snapshot, child_limited = _snapshot_node(child, active_ids)
            limited = limited or child_limited
            if _is_safe_segment(key):
                items.append((key, child_snapshot))
            else:
                unsafe_entries.append(_UnsafeEntrySnapshot(key=key, value=child_snapshot))
                limited = True
    finally:
        active_ids.remove(object_id)
    return _MappingSnapshot(tuple(items), tuple(unsafe_entries)), limited


def _snapshot_sequence(value: object, active_ids: set[int]) -> tuple[_SnapshotNode, bool]:
    object_id = id(value)
    if object_id in active_ids:
        return _OpaqueSnapshot(value), True

    active_ids.add(object_id)
    items: list[_SnapshotNode] = []
    limited = False
    try:
        for child in value:  # type: ignore[union-attr]
            child_snapshot, child_limited = _snapshot_node(child, active_ids)
            items.append(child_snapshot)
            limited = limited or child_limited
    finally:
        active_ids.remove(object_id)
    return _SequenceSnapshot(type(value), tuple(items)), limited


def _snapshot_set(value: object) -> _SnapshotNode:
    items: list[_ScalarSnapshot] = []
    for child in value:  # type: ignore[union-attr]
        if type(child) not in _SAFE_SCALAR_TYPES:
            return _OpaqueSnapshot(value)
        items.append(_ScalarSnapshot(type(child), child))
    return _SetSnapshot(type(value), tuple(items))


def _is_safe_segment(key: object) -> bool:
    return type(key) is str and bool(key) and all(character.isprintable() for character in key)


def _diff_nodes(
    before: _SnapshotNode,
    after: _SnapshotNode,
    path: MetaPath,
    builder: _DiffBuilder,
) -> None:
    if isinstance(before, _MappingSnapshot) and isinstance(after, _MappingSnapshot):
        _diff_mappings(before, after, path, builder)
        return
    if _nodes_equal(before, after):
        return
    _record_changed(path, builder)


def _diff_mappings(
    before: _MappingSnapshot,
    after: _MappingSnapshot,
    path: MetaPath,
    builder: _DiffBuilder,
) -> None:
    before_items = dict(before.items)
    after_items = dict(after.items)
    before_keys = set(before_items)
    after_keys = set(after_items)

    for key in before_keys - after_keys:
        builder.removed.append((*path, key))
    for key in after_keys - before_keys:
        builder.added.append((*path, key))
    for key in before_keys & after_keys:
        _diff_nodes(before_items[key], after_items[key], (*path, key), builder)

    if _unsafe_entries_equal(before.unsafe_entries, after.unsafe_entries):
        return
    builder.limited = True
    _record_changed(path, builder)


def _nodes_equal(before: _SnapshotNode, after: _SnapshotNode) -> bool:
    if type(before) is not type(after):
        return False
    if isinstance(before, _ScalarSnapshot) and isinstance(after, _ScalarSnapshot):
        return _scalars_equal(before, after)
    if isinstance(before, _OpaqueSnapshot) and isinstance(after, _OpaqueSnapshot):
        return before.value is after.value
    if isinstance(before, _SequenceSnapshot) and isinstance(after, _SequenceSnapshot):
        return _sequences_equal(before, after)
    if isinstance(before, _SetSnapshot) and isinstance(after, _SetSnapshot):
        return _sets_equal(before, after)
    if isinstance(before, _MappingSnapshot) and isinstance(after, _MappingSnapshot):
        return _mappings_equal(before, after)
    return False


def _scalars_equal(before: _ScalarSnapshot, after: _ScalarSnapshot) -> bool:
    if before.value_type is not after.value_type:
        return False
    if before.value_type is float:
        return _float_equal(before.value, after.value)
    if before.value_type is complex:
        return _complex_equal(before.value, after.value)
    return bool(before.value == after.value)


def _float_equal(before: object, after: object) -> bool:
    before_float = before  # exact built-in floats are guaranteed by the caller
    after_float = after
    if math.isnan(before_float) and math.isnan(after_float):  # type: ignore[arg-type]
        return True
    return bool(before_float == after_float)


def _complex_equal(before: object, after: object) -> bool:
    before_complex = before  # exact built-in complex values are guaranteed by the caller
    after_complex = after
    real_equal = _float_equal(before_complex.real, after_complex.real)  # type: ignore[union-attr]
    imaginary_equal = _float_equal(before_complex.imag, after_complex.imag)  # type: ignore[union-attr]
    return real_equal and imaginary_equal


def _sequences_equal(before: _SequenceSnapshot, after: _SequenceSnapshot) -> bool:
    if before.value_type is not after.value_type or len(before.items) != len(after.items):
        return False
    return all(_nodes_equal(left, right) for left, right in zip(before.items, after.items))


def _sets_equal(before: _SetSnapshot, after: _SetSnapshot) -> bool:
    if before.value_type is not after.value_type or len(before.items) != len(after.items):
        return False
    unmatched = list(after.items)
    for before_item in before.items:
        match_index = next(
            (index for index, after_item in enumerate(unmatched) if _scalars_equal(before_item, after_item)),
            None,
        )
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return True


def _mappings_equal(before: _MappingSnapshot, after: _MappingSnapshot) -> bool:
    before_items = dict(before.items)
    after_items = dict(after.items)
    if before_items.keys() != after_items.keys():
        return False
    if any(not _nodes_equal(before_items[key], after_items[key]) for key in before_items):
        return False
    return _unsafe_entries_equal(before.unsafe_entries, after.unsafe_entries)


def _unsafe_entries_equal(
    before: tuple[_UnsafeEntrySnapshot, ...],
    after: tuple[_UnsafeEntrySnapshot, ...],
) -> bool:
    if len(before) != len(after):
        return False
    unmatched = list(after)
    for before_entry in before:
        match_index = next(
            (
                index
                for index, after_entry in enumerate(unmatched)
                if before_entry.key is after_entry.key
                and _nodes_equal(before_entry.value, after_entry.value)
            ),
            None,
        )
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return True


def _record_changed(path: MetaPath, builder: _DiffBuilder) -> None:
    if path:
        builder.changed.append(path)
    else:
        builder.limited = True


def _sorted_paths(paths: list[MetaPath]) -> tuple[MetaPath, ...]:
    return tuple(sorted(set(paths), key=_render_path))


def _render_path(path: MetaPath) -> str:
    return ".".join(path)


def _append_paths(lines: list[str], label: str, paths: tuple[MetaPath, ...]) -> None:
    if not paths:
        lines.append(f"  {label}: []")
        return
    lines.append(f"  {label}:")
    lines.extend(f"    - {_render_path(path)}" for path in paths)
