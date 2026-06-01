"""Shared reader for the ``_meta.legend_blocks`` schema.

Owns the schema walk (name-resolution by mapping key, non-empty entries list,
per-entry mapping + non-empty token validation) used by both
``cell_codec.scalar._legend_tokens`` and ``compact_multiaxis._legend_groups``.
Yields validated ``(token, group_value)`` records; each caller picks what it
needs.

Canonical ``_meta.legend_blocks`` is mapping form only. External list-form
authoring is normalized once at the ``domain.ingress`` boundary
(``FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5``); this reader therefore
resolves a block only by mapping key and does not carry a second list-shape
compatibility surface.

This module is private to the transformations layer. It exists only to
remove the duplicated schema walk; it does not define a public legend-block
API.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from spreadsheet_handling.domain._cell_primitives import _is_empty_cell


def _read_legend_block(
    meta: Mapping[str, Any] | None,
    legend_name: str,
) -> list[tuple[Any, Any]]:
    """Return ``[(token, group_value), ...]`` for a configured legend block.

    Raises ``KeyError`` when ``meta`` is missing or the named legend block
    cannot be found. Raises ``ValueError`` when the entries list is invalid
    or any individual entry is malformed. Tokens are validated as non-empty
    via :func:`_is_empty_cell`; the ``group`` field defaults to ``""``.
    """
    if not isinstance(meta, Mapping):
        raise KeyError(
            f"allowed_from_legend references legend block {legend_name!r}, "
            "but _meta.legend_blocks is missing"
        )
    raw = meta.get("legend_blocks")
    spec = raw.get(legend_name) if isinstance(raw, Mapping) else None

    if not isinstance(spec, Mapping):
        raise KeyError(
            f"allowed_from_legend references legend block {legend_name!r}, "
            "but no matching legend block was found in _meta.legend_blocks"
        )
    entries = spec.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Legend block {legend_name!r} requires a non-empty entries list")

    records: list[tuple[Any, Any]] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, Mapping):
            raise ValueError(f"Legend block {legend_name!r} entry {index} must be a mapping")
        token = entry.get("token")
        if _is_empty_cell(token):
            raise ValueError(f"Legend block {legend_name!r} entry {index} has an empty token")
        group_value = entry.get("group", "")
        records.append((token, group_value))
    return records
