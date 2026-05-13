# src/spreadsheet_handling/pipeline/runner.py
from __future__ import annotations

from typing import Any

from ..io_backends.router import get_loader, get_saver
from .build import build_steps_from_config
from .config import AppConfig
from .execution import run_pipeline as _run_pipeline


def run_app(app: AppConfig, run_id: str | None = None, **_: object) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """
    Run I/O and optional pipeline steps.
    Returns: (frames, meta, issues)
    """
    io = app.io

    # --- Select input (use the first named input) ---
    if not io.inputs:
        raise SystemExit("No inputs configured.")
    inp_name, inp = next(iter(io.inputs.items()))
    loader = get_loader(inp.kind)

    # Loaders may accept 'options'; backends handle None themselves.
    frames = loader(inp.path, options=getattr(inp, "options", None))

    # --- Bind steps (may be empty) ---
    step_specs = app.pipeline or []
    bound_steps = build_steps_from_config(step_specs) if step_specs else []

    # --- Execute only when steps are present ---
    if bound_steps:
        frames = _run_pipeline(frames, bound_steps)

    # --- Write output ---
    out = io.output
    saver = get_saver(out.kind)
    saver(frames, out.path, options=getattr(out, "options", None))

    # Meta/issues are still empty; keep the API stable.
    return frames, {}, []
