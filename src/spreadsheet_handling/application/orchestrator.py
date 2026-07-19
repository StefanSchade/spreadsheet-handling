from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, TypeAlias

import logging

from ..domain.pipeline_cleanup import execute_final_domain_cleanup
from ..io_backends.router import get_loader, get_saver
from ..pipeline.execution import run_pipeline
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
    """
    inp = _coerce_io(input, "input")
    out = _coerce_io(output, "output")

    log.info("orchestrate: loading input kind=%s path=%s", inp.kind, inp.path)
    frames = _load_frames(inp, header_levels=header_levels)

    if steps:
        step_list = list(steps)
        log.info("orchestrate: running %d step(s)", len(step_list))
        frames = run_pipeline(frames, step_list)

    # Final domain cleanup: execute pending explicit cleanup commands
    # (_meta.pipeline_cleanup) and consume them. Carrier-neutral; runs for
    # every output kind, immediately before the persistence boundary. Like
    # the persistence boundary below, this is part of the orchestrator's
    # macro flow, not a configurable pipeline step. It executes only
    # explicit drop/keep declarations and never infers cleanup from
    # lifecycle roles. See
    # src/spreadsheet_handling/domain/pipeline_cleanup.py.
    frames = execute_final_domain_cleanup(frames)

    # Persistence boundary: project runtime _meta onto its persistable
    # contract before any backend writes anything. Carrier-neutral; runs for
    # every output kind. The boundary is part of the orchestrator's macro
    # flow, not a configurable pipeline step. See
    # docs/semantic_model/08_lifecycle_and_update_semantics.adoc and
    # src/spreadsheet_handling/pipeline/persistence_boundary.py.
    meta = frames.get("_meta")
    if isinstance(meta, dict):
        frames = dict(frames)
        frames["_meta"] = project_meta_to_persistable_contract(meta)

    log.info("orchestrate: writing output kind=%s path=%s", out.kind, out.path)
    _save_frames(out, frames)
    return frames
