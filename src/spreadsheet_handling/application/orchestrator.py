from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

import logging
import pandas as pd

from ..pipeline.registry import run_pipeline
from ..pipeline.types import BoundStep, Frames

# Backends (existing adapters)
from ..io_backends.json_backend import JSONBackend
from ..io_backends.xml_backend import XMLBackend
from ..io_backends.yaml_backend import load_yaml_dir as _yaml_load, save_yaml_dir as _yaml_save
from ..io_backends.xlsx.xlsx_backend import ExcelBackend

log = logging.getLogger("sheets.orchestrator")


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
    if inp.kind in {"json", "json_dir"}:
        return JSONBackend().read_multi(inp.path, header_levels=header_levels, options=inp.options)
    if inp.kind in {"xml", "xml_dir"}:
        return XMLBackend().read_multi(inp.path, header_levels=header_levels, options=inp.options)
    if inp.kind in {"yaml", "yaml_dir"}:
        return _yaml_load(inp.path)
    if inp.kind in {"xlsx", "excel"}:
        return ExcelBackend().read_multi(inp.path, header_levels=header_levels, options=inp.options)
    raise ValueError(f"Unsupported input kind: {inp.kind!r}")

def _save_frames(out: IODesc, frames: Frames) -> None:
    if out.kind in {"json", "json_dir"}:
        JSONBackend().write_multi(frames, out.path, options=out.options)
        return
    if out.kind in {"xml", "xml_dir"}:
        XMLBackend().write_multi(frames, out.path, options=out.options)
        return
    if out.kind in {"yaml", "yaml_dir"}:
        _yaml_save(frames, out.path)
        return
    if out.kind in {"xlsx", "excel"}:
        ExcelBackend().write_multi(frames, out.path, options=out.options)
        return
    raise ValueError(f"Unsupported output kind: {out.kind!r}")


# ---------------------------
# Public API
# ---------------------------

def orchestrate(
    *,
    input: Mapping[str, Any],
    output: Mapping[str, Any],
    steps: Iterable[BoundStep] | None = None,
    header_levels: int = 1,
) -> Frames:
    """
    Unified execution engine for sheets-run and the CLI shims.

    - Loads frames from 'input' backend (json_dir | yaml_dir | xlsx).
    - Runs the given 'steps' (pure Frames→Frames, optional).
    - Writes frames to 'output' backend.
    - Returns the final frames for in-process reuse/testing.

    Parameters
    ----------
    input : Mapping[str, Any]
        { kind: "json_dir"|"yaml_dir"|"xlsx", path: str, options?: {...} }
    output : Mapping[str, Any]
        { kind: "json_dir"|"yaml_dir"|"xlsx", path: str, options?: {...} }
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

    log.info("orchestrate: writing output kind=%s path=%s", out.kind, out.path)
    _save_frames(out, frames)
    return frames
