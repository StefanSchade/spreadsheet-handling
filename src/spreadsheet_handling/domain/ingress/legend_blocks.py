"""Legend Blocks shape-normalization rule for the domain ingress boundary.

External authoring accepts ``_meta.legend_blocks`` as either an
insertion-ordered mapping keyed by Legend Block identity, or a list of block
mappings whose identity is resolved from ``name`` / ``id`` / positional
fallback. List form is authoring sugar only: this rule normalizes it once, at
the external-to-domain ingress boundary, to the single canonical mapping form
so that no downstream domain transformation, renderer, validation pass,
persistence projector, or framework-produced carrier ever receives list form.

The rule is a pure ``Frames -> Frames`` transformation. It never mutates the
caller's ``frames``, ``_meta``, the ``legend_blocks`` container, or any block
mapping; it validates and constructs the complete candidate result before
returning it, so a shape or duplicate-identity failure leaves the input object
graph unchanged.

Entry-value semantics (token validity, labels, duplicate entry tokens, empty
entries, unknown references, unhashable tokens) are deliberately *not* decided
here; they belong to ``FTR-LEGEND-BLOCKS-ENTRY-CONTRACT-P5``. This rule only
canonicalizes the block-container shape and drops the render-derived
``resolved`` Resolution facet (never durable Intent).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

Frames = dict[str, Any]

_ROOT_KEY = "legend_blocks"
_RESOLVED_KEY = "resolved"


def normalize_legend_blocks_shape(frames: Frames) -> Frames:
    """Return ``frames`` with ``_meta.legend_blocks`` in canonical mapping form.

    A no-op when there is no ``_meta`` mapping or no ``legend_blocks`` root.
    List form becomes an insertion-ordered mapping keyed by resolved identity;
    mapping form is preserved value-for-value (field order included). In both
    forms a pre-existing ``resolved`` facet is removed from every block.

    Raises ``ValueError`` for a non-mapping list member, a duplicate resolved
    identity, or a root that is neither a mapping nor a list.
    """
    meta = frames.get("_meta")
    if not isinstance(meta, Mapping) or _ROOT_KEY not in meta:
        return frames

    raw = meta[_ROOT_KEY]
    normalized = _normalize_root(raw)
    if normalized is None:
        # Degenerate empty root (``None``); treat as absent and leave untouched.
        return frames

    new_meta = dict(meta)
    new_meta[_ROOT_KEY] = normalized
    new_frames = dict(frames)
    new_frames["_meta"] = new_meta
    return new_frames


def _normalize_root(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        return _normalize_mapping(raw)
    if isinstance(raw, list):
        return _normalize_list(raw)
    raise ValueError(
        "_meta.legend_blocks must be a mapping or a list of mappings, "
        f"got {type(raw).__name__}"
    )


def _normalize_mapping(raw: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for name, block in raw.items():
        normalized[name] = _strip_resolved(block)
    return normalized


def _normalize_list(raw: list[Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(
                "_meta.legend_blocks list member at position "
                f"{position} must be a mapping, got {type(item).__name__}"
            )
        identity = _resolve_identity(item, position)
        if identity in normalized:
            raise ValueError(
                "_meta.legend_blocks list member at position "
                f"{position} resolves to duplicate legend block identity {identity!r}"
            )
        normalized[identity] = _strip_resolved(item)
    return normalized


def _resolve_identity(item: Mapping[str, Any], position: int) -> str:
    # Preserve the existing compatibility expression exactly, including its
    # truthiness and positional fallback behavior.
    return str(item.get("name") or item.get("id") or f"legend_{position}")


def _strip_resolved(block: Any) -> Any:
    if not isinstance(block, Mapping):
        return block
    # Shallow copy that drops ``resolved`` while preserving field order. Nested
    # containers (entries, placement) are shared but never mutated here.
    return {key: value for key, value in block.items() if key != _RESOLVED_KEY}


__all__ = ["normalize_legend_blocks_shape"]
