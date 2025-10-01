from __future__ import annotations

from importlib import import_module
from typing import Callable, Dict, Any, Tuple, Union

import pandas as pd

from .config import load_app_config, AppConfig, StepRef
from ..io_backends.router import make_backend
from ..io_backends.base import BackendOptions

Frames = Dict[str, pd.DataFrame]
MetaDict = Dict[str, Any]
Issues = list[dict[str, Any]]


def _load_callable(dotted: str) -> Callable[..., Callable[[Frames], Frames]]:
    """
    Load a step factory from a dotted reference.
    Accepts either "pkg.mod:factory" or "pkg.mod.factory".
    """
    if ":" in dotted:
        mod_name, sym = dotted.split(":", 1)
    else:
        mod_name, sym = dotted.rsplit(".", 1)
    mod = import_module(mod_name)
    fn = getattr(mod, sym)
    return fn


def _apply_steps(frames: Frames, steps: list[StepRef]) -> Frames:
    out = frames
    for step in steps:
        factory = _load_callable(step.dotted)
        bound = factory(**(step.args or {}))  # returns Callable[[Frames], Frames]
        out = bound(out)
    return out


def run_pipeline(
        cfg_or_path: Union[str, AppConfig],
        *,
        run_id: str | None = None,            # accepted but ignored for now
) -> Tuple[Frames, MetaDict, Issues]:
    """
    Minimal pipeline runner used by tests:
    - Accepts either a config PATH (str) or a pre-built AppConfig
    - Reads inputs via IO backends
    - Applies dotted step factories
    - Writes to the configured output backend
    - Returns (frames, meta, issues)
    """
    app: AppConfig = (
        load_app_config(cfg_or_path) if isinstance(cfg_or_path, str) else cfg_or_path
    )

    # 1) read all inputs (merge by sheet name; last one wins on conflicts)
    all_frames: Frames = {}
    for _, endpoint in app.io.inputs.items():
        backend = make_backend(endpoint.kind)
        opts = BackendOptions()  # extend as needed
        frames = backend.read_multi(endpoint.path, header_levels=1, options=opts)
        all_frames.update(frames)

    # 2) pipeline steps
    result: Frames = _apply_steps(all_frames, app.pipeline.steps)

    # 3) write output
    out_backend = make_backend(app.io.output.kind)
    out_opts = BackendOptions()
    out_backend.write_multi(result, app.io.output.path, options=out_opts)

    # 4) meta + issues (placeholder)
    meta: MetaDict = {}
    issues: Issues = []

    return result, meta, issues
