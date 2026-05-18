"""Target/source pattern handling and frame-name derivation.

Pattern (in)validation, safe frame-name generation, value-map entry
resolution, and discriminator-value extraction from frame names. Verbatim move
out of the former single ``discriminator_split`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-DISCRIMINATOR-P5).

Dependency edges: ``naming -> values`` and ``naming -> framecheck``. The
``framecheck`` edge exists solely because ``_value_map_entries`` validates
generated frame-name uniqueness via the structural ``_ensure_unique_target_frames``
check; it is acyclic (``framecheck`` is a leaf) and required by a verbatim move,
not a semantic change.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .framecheck import _ensure_unique_target_frames
from .values import _plain_value, _valid_discriminator_value, _values_equal

_PLACEHOLDER = "{value}"
_INVALID_SEGMENT_CHARS = set("/\\[]:*?")


def _value_map_entries(value_map: Mapping[Any, str] | None) -> list[tuple[Any, str]]:
    if not isinstance(value_map, Mapping) or not value_map:
        raise ValueError("value_map must be a non-empty mapping")
    entries: list[tuple[Any, str]] = []
    frame_names: list[str] = []
    for raw_value, raw_frame_name in value_map.items():
        value = _valid_discriminator_value(
            raw_value,
            frame_name="value_map",
            column_name="value_map",
            row_number=len(entries) + 1,
        )
        frame_name = _valid_frame_name(raw_frame_name)
        if any(_values_equal(existing, value) for existing, _ in entries):
            raise ValueError(f"value_map contains duplicate value {value!r}")
        entries.append((value, frame_name))
        frame_names.append(frame_name)
    _ensure_unique_target_frames(frame_names)
    return entries


def _mapped_frame_name(mapped_values: list[tuple[Any, str]] | None, value: Any) -> str:
    assert mapped_values is not None
    for mapped_value, frame_name in mapped_values:
        if _values_equal(mapped_value, value):
            return frame_name
    raise ValueError(f"Discriminator value {value!r} is missing from value_map")


def _frame_for_value(entries: list[dict[str, Any]], value: Any) -> str:
    for entry in entries:
        if _values_equal(entry["value"], value):
            return entry["frame"]
    raise ValueError(f"Discriminator value {value!r} is not configured")


def _ensure_pattern(pattern: str, field_name: str) -> None:
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if pattern.count(_PLACEHOLDER) != 1:
        raise ValueError(f"{field_name} must contain exactly one {_PLACEHOLDER!r} placeholder")
    remainder = pattern.replace(_PLACEHOLDER, "")
    if "{" in remainder or "}" in remainder:
        raise ValueError(f"{field_name} contains unsupported format placeholders")


def _pattern_parts(pattern: str) -> tuple[str, str]:
    _ensure_pattern(pattern, "pattern")
    before, after = pattern.split(_PLACEHOLDER, 1)
    return before, after


def _try_value_from_frame_name(pattern: str, frame_name: str) -> str | None:
    before, after = _pattern_parts(pattern)
    if not frame_name.startswith(before) or not frame_name.endswith(after):
        return None
    value = frame_name[len(before) : len(frame_name) - len(after) if after else len(frame_name)]
    if value == "":
        return None
    return value


def _value_from_frame_name(pattern: str, frame_name: str) -> str:
    value = _try_value_from_frame_name(pattern, frame_name)
    if value is None:
        raise ValueError(f"Source frame {frame_name!r} does not match pattern {pattern!r}")
    return value


def _safe_value_segment(value: Any) -> str:
    segment = str(_plain_value(value))
    if (
        not segment
        or segment.strip() != segment
        or any(char in _INVALID_SEGMENT_CHARS for char in segment)
        or any(ord(char) < 32 for char in segment)
    ):
        raise ValueError(
            f"Discriminator value {value!r} is not safe for target_pattern; provide value_map"
        )
    return segment


def _valid_frame_name(frame_name: Any) -> str:
    if not isinstance(frame_name, str) or not frame_name.strip():
        raise ValueError("Generated frame names must be non-empty strings")
    if any(ord(char) < 32 for char in frame_name):
        raise ValueError(f"Generated frame name {frame_name!r} contains control characters")
    return frame_name
