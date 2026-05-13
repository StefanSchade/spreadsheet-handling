"""Linear pipeline execution for already-bound steps."""

from __future__ import annotations

import logging
from typing import Iterable

from .types import Frames, Step

log = logging.getLogger("sheets.pipeline")


def run_pipeline(frames: Frames, steps: Iterable[Step]) -> Frames:
    out = frames
    for step in steps:
        log.debug(
            "-> step: %s config=%s",
            getattr(step, "name", "<unnamed>"),
            getattr(step, "config", {}),
        )
        out = step(out)
    return out
