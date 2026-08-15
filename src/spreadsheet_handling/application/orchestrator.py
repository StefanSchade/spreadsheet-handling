from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, TypeAlias

import logging

from .managed_pipeline import (
    ManagedExecutionState,
    establish_initial_state,
    finalize_managed_state,
    run_managed_steps,
)
from ..domain.pipeline_cleanup import execute_final_domain_cleanup
from ..io_backends.router import get_loader, get_saver
from ..pipeline.persistence_boundary import project_meta_to_persistable_contract
from ..pipeline.types import BoundStep, Frames

log = logging.getLogger("sheets.orchestrator")

IODescriptorLike: TypeAlias = Mapping[str, Any]


# ---------------------------
# Small typed config holders
# ---------------------------


@dataclass(frozen=True)
class IODesc:
    kind: str
    path: str
    options: Dict[str, Any] | None = None


def _coerce_io(d: Mapping[str, Any] | None, role: str) -> IODesc:
    if not d:
        raise ValueError(f"Missing '{role}' I/O descriptor")
    kind = str(d.get("kind") or "").strip().lower()
    path = str(d.get("path") or "").strip()
    opts = dict(d.get("options") or {})
    if not kind or not path:
        raise ValueError(f"Invalid '{role}' I/O descriptor: need 'kind' and 'path'")
    return IODesc(kind=kind, path=path, options=opts or None)


# ---------------------------
# Backend routing
# ---------------------------


def _load_frames(inp: IODesc, *, header_levels: int = 1) -> Frames:
    try:
        loader = get_loader(inp.kind)
    except ValueError as exc:
        raise ValueError(f"Unsupported input kind: {inp.kind!r}") from exc
    return loader(inp.path, options=inp.options, header_levels=header_levels)


def _save_frames(out: IODesc, frames: Frames) -> None:
    try:
        saver = get_saver(out.kind)
    except ValueError as exc:
        raise ValueError(f"Unsupported output kind: {out.kind!r}") from exc
    saver(frames, out.path, options=out.options)


def _finalize_and_persist(frames: Frames, managed_state: ManagedExecutionState, out: IODesc) -> Frames:
    """Final domain cleanup, E5 state closure, persistence boundary, save.

    Carrier-neutral; runs for every output kind. Each phase is part of the
    orchestrator's macro flow, not a configurable pipeline step:

    * final domain cleanup executes pending explicit ``_meta.pipeline_cleanup``
      commands (``domain.pipeline_cleanup``);
    * E5 state closure (``managed_pipeline.finalize_managed_state``)
      terminates every controlled role whose frame cleanup removed, then
      authorizes every role still live against the exact sink kind -- raising
      before any saver runs if a controlled role (FormulaSpec, GroupedMatrix,
      or the artifact-manifest ``source_frames`` role) has no exact reviewed
      consuming transition for this sink;
    * the persistence boundary projects runtime ``_meta`` onto its
      persistable contract immediately before the saver runs
      (``pipeline.persistence_boundary``).
    """
    frames_before_cleanup = frames
    frames = execute_final_domain_cleanup(frames)
    frames = finalize_managed_state(frames_before_cleanup, frames, managed_state, sink_kind=out.kind)

    meta = frames.get("_meta")
    if isinstance(meta, dict):
        frames = dict(frames)
        frames["_meta"] = project_meta_to_persistable_contract(meta)
    return frames


# ---------------------------
# Public API
# ---------------------------


def orchestrate(
    *,
    input: IODescriptorLike,
    output: IODescriptorLike,
    steps: Iterable[BoundStep] | None = None,
    header_levels: int = 1,
) -> Frames:
    """
    Unified execution engine for sheets-run and reference shortcut commands.

    - Loads frames from 'input' backend (csv_dir | json_dir | yaml_dir | xml_dir | xlsx | ods | calc).
    - Runs the given 'steps' (pure Frames→Frames, optional).
    - Writes frames to 'output' backend.
    - Returns the final frames for in-process reuse/testing.

    Parameters
    ----------
    input : Mapping[str, Any]
        { kind: "csv_dir"|"json_dir"|"yaml_dir"|"xml_dir"|"xlsx"|"ods"|"calc", path: str, options?: {...} }
    output : Mapping[str, Any]
        { kind: "csv_dir"|"json_dir"|"yaml_dir"|"xml_dir"|"xlsx"|"ods"|"calc", path: str, options?: {...} }
    steps : Iterable[BoundStep] | None
        List of bound steps (use factories from pipeline to build them).
    header_levels : int
        Desired header levels on read; 1 by default.

    Raises
    ------
    ValueError for invalid I/O descriptors or unknown kinds.

    Programmatic surface contract (Trusted Ingress slice E6, ``docs/backlog/
    FTR-TRUSTED-INGRESS-P4A.adoc`` sections 23/46): this is the one
    framework-managed macro seam every router-backed entry point
    (``sheets-run``, :func:`spreadsheet_handling.pipeline.runner.run_app`,
    the ``spreadsheet_handling.orchestrator`` compatibility shim,
    ``sheets-schema-maintain``/``application.schema_maintenance.
    run_schema_maintenance``) funnels through. It automatically establishes
    E1-E3 ordinary Trusted Ingress conformance before any configured step
    runs, applies E4/E5 controlled-role classification/transition around
    each step, and authorizes every surviving controlled role against the
    exact output sink kind before saving -- raising before the saver runs
    otherwise. Configured ``steps`` themselves remain a *trusted pipeline
    description*: this automatic payload-conformance establishment does not
    authorize an untrusted/less-trusted pipeline description (dotted
    plugin targets, YAML step configuration) -- that remains a separate,
    still-open concern (Phase-E slice E7). See ``docs/ai_info/
    interfaces_and_gates.adoc`` for the complete programmatic-surface
    matrix.
    """
    inp = _coerce_io(input, "input")
    out = _coerce_io(output, "output")

    log.info("orchestrate: loading input kind=%s path=%s", inp.kind, inp.path)
    frames = _load_frames(inp, header_levels=header_levels)

    # Initial ordinary conformance establishment (Trusted Ingress E1-E3,
    # wired here by E5) before any configured step; a rejection means zero
    # steps, zero cleanup, zero save. See domain/ingress/coordinator.py and
    # FTR-TRUSTED-INGRESS-P4A.adoc section 23 (E1-E5).
    frames, managed_state = establish_initial_state(frames)

    if steps:
        step_list = list(steps)
        log.info("orchestrate: running %d step(s)", len(step_list))
        # E5 macro wiring: classify each step against the exact E4
        # transition representation, execute it through the unmodified,
        # still step-only `run_pipeline`, and apply its declared
        # controlled-role transition -- or, absent an exact certified
        # transition, end all prior controlled-role authority and ordinarily
        # re-establish the return before the next step/cleanup/save. See
        # application/managed_pipeline.py.
        frames, managed_state = run_managed_steps(frames, managed_state, step_list)

    frames = _finalize_and_persist(frames, managed_state, out)

    log.info("orchestrate: writing output kind=%s path=%s", out.kind, out.path)
    _save_frames(out, frames)
    return frames
