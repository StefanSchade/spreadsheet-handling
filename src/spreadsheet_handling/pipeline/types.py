"""Canonical pipeline type definitions.

All pipeline-related types live here to avoid circular imports.
Other modules (steps, registry, runner) import from this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Protocol, TypedDict

import pandas as pd

# ---------------------------------------------------------------------------
# Core payload type
# ---------------------------------------------------------------------------

Frames = Dict[str, pd.DataFrame]


# ---------------------------------------------------------------------------
# Step protocol & bound step
# ---------------------------------------------------------------------------

class Step(Protocol):
    """A step transforms a map of frames into another map of frames."""
    name: str
    config: Dict[str, Any]

    def __call__(self, frames: Frames) -> Frames: ...


@dataclass(frozen=True)
class BoundStep:
    """
    Bound step (Name + Config + Callable).
    name/config are useful for logging, debugging, and introspection.
    fn encapsulates the actual logic (typically a closure from a factory).
    """
    name: str
    config: Dict[str, Any]
    fn: Callable[[Frames], Frames]

    def __call__(self, frames: Frames) -> Frames:
        return self.fn(frames)


# ---------------------------------------------------------------------------
# Step specification (for config binding)
# ---------------------------------------------------------------------------

class StepSpec(TypedDict, total=False):
    step: str
    name: str
    defaults: Dict[str, Any]
    mode_missing_fk: str
    mode_duplicate_ids: str
    prefix: str
    # plugin-specific
    func: str
    args: Dict[str, Any]
