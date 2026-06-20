"""Assessment scale mapping helpers for project_memory.

Lookup and validation for canonical/assessment_scale_mappings.json.
Unknown source values are not guessed — lookup returns None.
"""
from __future__ import annotations

from typing import Any


def build_lookup_index(
    mappings: list[dict[str, Any]],
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    """Build a fast-lookup dict keyed by (source_system, source_field, source_value, normalized_scale)."""
    index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for entry in mappings:
        key = (
            str(entry.get("source_system", "")),
            str(entry.get("source_field", "")),
            str(entry.get("source_value", "")),
            str(entry.get("normalized_scale", "")),
        )
        index[key] = entry
    return index


def lookup(
    mappings: list[dict[str, Any]],
    source_system: str,
    source_field: str,
    source_value: str,
    *,
    normalized_scale: str = "impact_0_5",
) -> dict[str, Any] | None:
    """Look up a normalized mapping entry. Returns None when there is no match."""
    index = build_lookup_index(mappings)
    return index.get((source_system, source_field, source_value, normalized_scale))


def validate_mappings(mappings: list[dict[str, Any]]) -> list[str]:
    """Validate mapping records. Returns a list of error messages (empty list means valid)."""
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str, str]] = set()

    for i, entry in enumerate(mappings):
        entry_id = str(entry.get("id", ""))

        if not entry_id:
            errors.append(f"Entry at index {i} has missing or empty 'id'.")
        elif entry_id in seen_ids:
            errors.append(f"Duplicate id: {entry_id!r}")
        else:
            seen_ids.add(entry_id)

        nv = entry.get("normalized_value")
        if nv is None:
            errors.append(f"Entry {entry_id!r} is missing 'normalized_value'.")
        elif not isinstance(nv, int):
            errors.append(
                f"Entry {entry_id!r}: 'normalized_value' must be an integer, got {type(nv).__name__}."
            )
        elif not (0 <= nv <= 5):
            errors.append(
                f"Entry {entry_id!r}: 'normalized_value' {nv} is outside the allowed range [0, 5]."
            )

        key = (
            str(entry.get("source_system", "")),
            str(entry.get("source_field", "")),
            str(entry.get("source_value", "")),
            str(entry.get("normalized_scale", "")),
        )
        if key in seen_keys:
            errors.append(
                f"Duplicate mapping key (source_system={key[0]!r}, source_field={key[1]!r}, "
                f"source_value={key[2]!r}, normalized_scale={key[3]!r}) in entry {entry_id!r}."
            )
        else:
            seen_keys.add(key)

    return errors
