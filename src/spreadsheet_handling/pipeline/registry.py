"""Step registry and configuration binding.

Maps step names (strings) to factory functions and provides
config-driven pipeline construction from dicts or YAML.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, Dict, Iterable, Mapping

from .types import BoundStep, Frames, Step

from .steps import (
    make_identity_step,
    make_validate_step,
    make_apply_fks_step,
    make_drop_helpers_step,
    make_check_fk_helpers_step,
    make_plugin_step,
    make_flatten_headers_step,
    make_unflatten_headers_step,
    make_reorder_helpers_step,
    make_add_validations_step,
    make_bootstrap_meta_step,
    make_apply_overrides_step,
)

log = logging.getLogger("sheets.pipeline")


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(frames: Frames, steps: Iterable[Step]) -> Frames:
    out = frames
    for step in steps:
        log.debug("-> step: %s config=%s", getattr(step, "name", "<unnamed>"), getattr(step, "config", {}))
        out = step(out)
    return out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

REGISTRY: Dict[str, Callable[..., BoundStep]] = {
    "identity":         make_identity_step,
    "validate":         make_validate_step,
    "apply_fks":        make_apply_fks_step,
    "drop_helpers":     make_drop_helpers_step,
    "check_fk_helpers": make_check_fk_helpers_step,
    "plugin":           make_plugin_step,
    "flatten_headers":  make_flatten_headers_step,
    "unflatten_headers": make_unflatten_headers_step,
    "reorder_helpers":  make_reorder_helpers_step,
    "add_validations":  make_add_validations_step,
    "bootstrap_meta":   make_bootstrap_meta_step,
    "apply_overrides":  make_apply_overrides_step,
}


# ---------------------------------------------------------------------------
# Config binding
# ---------------------------------------------------------------------------

def build_steps_from_config(step_specs: Iterable[Mapping[str, Any]]) -> list[BoundStep]:
    """
    Build steps from a config list like:
      - step: validate
        mode_duplicate_ids: warn
      - step: my_project.steps:make_extract_subset_step
        table: Orders
    Supported 'step' values:
      1) registry key (see REGISTRY)
      2) dotted path '<module>:<factory_function>'
    """
    def resolve_factory(step_id: str) -> Callable[..., BoundStep] | None:
        factory = REGISTRY.get(step_id)
        if factory:
            return factory
        if ":" in step_id:
            mod_name, func_name = step_id.split(":", 1)
            mod = importlib.import_module(mod_name)
            factory = getattr(mod, func_name, None)
            if factory is None:
                raise AttributeError(f"Factory '{func_name}' not found in module '{mod_name}'")
            return factory
        return None

    steps: list[BoundStep] = []
    for raw in step_specs:
        spec = dict(raw)
        step_id = spec.pop("step", None)
        if not step_id:
            raise ValueError(f"Step spec missing 'step': {raw}")

        factory = resolve_factory(step_id)
        if not factory:
            raise KeyError(f"Unknown step '{step_id}'. Known registry keys: {list(REGISTRY)}")

        name = spec.pop("name", None)

        try:
            bound = factory(name=name, **spec) if name is not None else factory(**spec)  # type: ignore[arg-type]
        except TypeError:
            if name is not None:
                tmp = factory(**spec)  # type: ignore[arg-type]
                bound = BoundStep(name=name, config=tmp.config, fn=tmp.fn)
            else:
                raise
        steps.append(bound)
    return steps


# ---------------------------------------------------------------------------
# YAML convenience
# ---------------------------------------------------------------------------

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def build_steps_from_yaml(path: str) -> list[BoundStep]:
    """Load a pipeline spec from YAML (expects top-level key 'pipeline': [...])."""
    if yaml is None:
        raise RuntimeError("PyYAML not installed; install with [dev] or add pyyaml to deps.")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    specs = cfg.get("pipeline")
    if not isinstance(specs, list):
        raise ValueError(f"YAML missing 'pipeline' list: {path}")
    return build_steps_from_config(specs)
