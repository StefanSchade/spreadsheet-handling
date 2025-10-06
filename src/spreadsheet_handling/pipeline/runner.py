# src/spreadsheet_handling/pipeline/runner.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple, List

from ..io_backends.router import get_loader, get_saver
from .config import AppConfig, PipelineConfig
from . import pipeline as pl  # <- um Namenskollision mit dieser Datei zu vermeiden
from .pipeline import build_steps_from_config  # Steps aus Spezifikation binden


def run_pipeline(app: AppConfig, run_id: str | None = None, **_: object) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """
    Führt I/O + optionale Steps aus.
    Returns: (frames, meta, issues)
    """
    io = app.io

    # --- Input wählen (wir nehmen den ersten benannten Input) ---
    if not io.inputs:
        raise SystemExit("No inputs configured.")
    inp_name, inp = next(iter(io.inputs.items()))
    loader = get_loader(inp.kind)

    # Loader darf 'options' entgegennehmen; Backends ignorieren None selbst.
    frames = loader(inp.path, options=getattr(inp, "options", None))

    # --- Steps binden (können leer sein) ---
    step_specs = (app.pipeline.steps if app.pipeline else []) or []
    bound_steps = build_steps_from_config(step_specs) if step_specs else []

    # --- Ausführen (nur wenn Steps vorhanden) ---
    if bound_steps:
        frames = pl.run_pipeline(frames, bound_steps)

    # --- Output schreiben ---
    out = io.output
    saver = get_saver(out.kind)
    saver(frames, out.path, options=getattr(out, "options", None))

    # (Meta/Issues aktuell noch leer – API bleibt)
    return frames, {}, []
