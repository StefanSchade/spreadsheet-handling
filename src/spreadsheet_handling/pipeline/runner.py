from __future__ import annotations

import importlib
from typing import Callable, Dict, List, Tuple

import pandas as pd

from .config import AppConfig
from ..io_backends.router import get_loader, get_saver

Frames = Dict[str, pd.DataFrame]
Meta = Dict[str, dict]
Issues = List[str]


def _resolve_step(dotted: str, args: dict | None) -> Callable[[Frames], Frames]:
    """
    Load a step factory via dotted path and return a callable Frames->Frames.
    The factory may itself already be the step (callable) or return one.
    """
    mod_name, func_name = dotted.split(":", 1) if ":" in dotted else dotted.rsplit(".", 1)
    module = importlib.import_module(mod_name)
    factory = getattr(module, func_name)
    step = factory(**(args or {}))
    if not callable(step):
        raise TypeError(f"Step factory '{dotted}' did not return a callable step")
    return step


def run_pipeline(app: AppConfig, run_id: str | None = None, **_: object) -> Tuple[Frames, Meta, Issues]:
    """
    Minimal orchestrator:
      - load frames from primary input
      - apply steps in order (each step: Frames -> Frames)
      - save frames to output
      - return (frames, empty meta, empty issues)

    Parameters
    ----------
    app : AppConfig
        The application configuration (I/O + pipeline).
    run_id : str | None
        Optional identifier accepted for compatibility; currently not used.
    **_ : object
        Swallows unknown kwargs for forward/backward compat with callers.
    """
    # Input: expect key 'primary'
    if "primary" not in app.io.inputs:
        raise KeyError("AppConfig.io.inputs must contain a 'primary' endpoint")

    inp = app.io.inputs["primary"]
    out = app.io.output

    loader = get_loader(inp.kind)
    saver = get_saver(out.kind)

    frames: Frames = loader(inp.path)

    # Steps
    for s in app.pipeline.steps:
        dotted = s.dotted or s.name  # tolerate either key
        step = _resolve_step(dotted, s.args or {})
        frames = step(frames)

    # Persist
    saver(frames, out.path)

    meta: Meta = {}
    issues: Issues = []
    return frames, meta, issues
