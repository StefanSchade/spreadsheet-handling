# src/spreadsheet_handling/pipeline/runner.py
from __future__ import annotations

from typing import Any

from .build import build_steps_from_config
from .config import AppConfig


def run_app(
    app: AppConfig,
    run_id: str | None = None,
    **_: object,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """
    Run I/O and optional pipeline steps via the orchestrator.

    Thin compatibility adapter over :func:`spreadsheet_handling.application.
    orchestrator.orchestrate`. ``AppConfig`` is unpacked into the
    orchestrator's input/output/steps surface so that ``run_app`` keeps a
    single source of truth for load/step/save semantics -- including the
    persistence boundary that projects runtime ``_meta`` onto its
    persistable contract immediately before save.

    Returns: ``(frames, meta, issues)``.
    """
    # Local import: ``application.orchestrator`` pulls in modules that
    # transitively import ``pipeline`` at package load, which would close a
    # cycle if this import happened at module top.
    from ..application.orchestrator import orchestrate

    io = app.io

    if not io.inputs:
        raise SystemExit("No inputs configured.")
    _inp_name, inp = next(iter(io.inputs.items()))

    step_specs = app.pipeline or []
    bound_steps = build_steps_from_config(step_specs) if step_specs else []

    out = io.output

    frames = orchestrate(
        input={
            "kind": inp.kind,
            "path": inp.path,
            "options": getattr(inp, "options", None),
        },
        output={
            "kind": out.kind,
            "path": out.path,
            "options": getattr(out, "options", None),
        },
        steps=bound_steps or None,
        header_levels=getattr(inp, "header_levels", 1),
    )

    # Meta/issues are still empty; keep the API stable.
    return frames, {}, []
