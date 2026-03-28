"""Bootstrap domain meta with fault-tolerant merging.

Implements the precedence model from FTR-META-BOOTSTRAP:
  1. Persistence  – existing meta from frames (or {} if missing)
  2. Profile       – defaults from pipeline profile
  3. CLI/Runtime   – explicit overrides (highest priority)
"""
from __future__ import annotations

from typing import Any, Dict


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Return a new dict with *overlay* merged on top of *base*.

    - Dict values are merged recursively.
    - All other values (lists, scalars) in *overlay* replace *base*.
    """
    result = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _get_meta(frames: Any) -> dict:
    """Extract meta from *frames* using the dual-interface convention."""
    if hasattr(frames, "meta"):
        return dict(frames.meta or {})
    if isinstance(frames, dict):
        return dict(frames.get("_meta") or {})
    return {}


def _set_meta(frames: Any, meta: dict) -> None:
    """Write *meta* back to *frames*."""
    if hasattr(frames, "meta"):
        frames.meta = meta
    elif isinstance(frames, dict):
        frames["_meta"] = meta


def bootstrap_meta(
    frames: Any,
    *,
    profile_defaults: Dict[str, Any] | None = None,
    cli_overrides: Dict[str, Any] | None = None,
) -> Any:
    """Merge meta from multiple sources and write back to *frames*.

    Precedence (later overwrites earlier):
      1. *profile_defaults* form the baseline.
      2. Persisted meta overwrites profile defaults.
      3. *cli_overrides* overwrite everything.

    Returns *frames* (mutated in place).
    """
    persisted = _get_meta(frames)

    # Start with profile defaults, then let persisted values win
    if profile_defaults:
        merged = _deep_merge(profile_defaults, persisted)
    else:
        merged = persisted

    # CLI overrides always win
    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)

    _set_meta(frames, merged)
    return frames
