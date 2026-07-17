"""Linear pipeline execution for already-bound steps."""

from __future__ import annotations

import logging
from typing import Iterable

from ._meta_change_trace import MetaSnapshot, diff_meta, format_meta_diff, snapshot_meta
from .types import Frames, Step

log = logging.getLogger("sheets.pipeline")


def run_pipeline(frames: Frames, steps: Iterable[Step]) -> Frames:
    out = frames
    for step in steps:
        step_name = getattr(step, "name", "<unnamed>")
        log.debug(
            "-> step: %s config=%s",
            step_name,
            getattr(step, "config", {}),
        )
        trace_enabled = log.isEnabledFor(logging.DEBUG)
        before = _snapshot_before_step(out) if trace_enabled else None
        out = step(out)
        if trace_enabled:
            _log_meta_change(step_name, before, out)
    return out


def _snapshot_before_step(frames: Frames) -> MetaSnapshot | None:
    try:
        return snapshot_meta(frames)
    except Exception:
        return None


def _log_meta_change(step_name: object, before: MetaSnapshot | None, frames: Frames) -> None:
    safe_step_name = _safe_step_name(step_name)
    try:
        if before is None:
            raise RuntimeError("before-step diagnostic unavailable")
        after = snapshot_meta(frames)
        diff = diff_meta(before, after)
        summary = format_meta_diff(safe_step_name, diff)
        log.debug("%s", summary)
    except Exception:
        _log_meta_limitation(safe_step_name)


def _safe_step_name(step_name: object) -> str:
    if type(step_name) is str and step_name and all(character.isprintable() for character in step_name):
        return step_name
    return "<unnamed>"


def _log_meta_limitation(step_name: str) -> None:
    try:
        log.debug("<- step: %s\nmeta: diagnostic limited", step_name)
    except Exception:
        pass
