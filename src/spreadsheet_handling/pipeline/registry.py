"""Step registry and configuration binding.

Maps step names (strings) to factory functions and provides
config-driven pipeline construction from dicts or YAML.
"""
from __future__ import annotations

import logging
import importlib
from typing import Any, Callable, Dict, Iterable, Mapping

from .types import BoundStep, Frames, Step, StepFactory, StepRegistration

from .steps import (
    make_builder_target_step,
    make_frames_target_step,
    make_identity_step,
    make_validate_step,
    make_apply_fks_step,
    make_drop_helpers_step,
    make_check_fk_helpers_step,
    make_plugin_step,
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

REGISTRY: Dict[str, StepRegistration | StepFactory] = {
    "identity":         make_identity_step,
    "validate":         make_validate_step,
    "apply_fks":        make_apply_fks_step,
    "drop_helpers":     make_drop_helpers_step,
    "check_fk_helpers": make_check_fk_helpers_step,
    "plugin":           make_plugin_step,
    "flatten_headers": StepRegistration(
        factory=make_builder_target_step,
        target="spreadsheet_handling.domain.transformations.helpers:flatten_headers",
    ),
    "unflatten_headers": StepRegistration(
        factory=make_builder_target_step,
        target="spreadsheet_handling.domain.transformations.helpers:unflatten_headers",
    ),
    "reorder_helpers": StepRegistration(
        factory=make_builder_target_step,
        target="spreadsheet_handling.domain.transformations.helpers:reorder_helpers_next_to_fk",
    ),
    "add_validations": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.validations.validate_columns:add_validations",
    ),
    "bootstrap_meta": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.meta_bootstrap:bootstrap_meta",
    ),
    "apply_overrides": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.yaml_overrides:load_and_apply_overrides",
    ),
    "expand_xref": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.xref_crosstable:expand_xref",
    ),
    "contract_xref": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.xref_crosstable:contract_xref",
    ),
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
    def resolve_registration(step_id: str) -> StepRegistration | None:
        entry = REGISTRY.get(step_id)
        if entry:
            return entry if isinstance(entry, StepRegistration) else StepRegistration(factory=entry)
        if ":" in step_id:
            mod_name, func_name = step_id.split(":", 1)
            mod = importlib.import_module(mod_name)
            factory = getattr(mod, func_name, None)
            if factory is None:
                raise AttributeError(f"Factory '{func_name}' not found in module '{mod_name}'")
            return StepRegistration(factory=factory)
        return None

    steps: list[BoundStep] = []
    for raw in step_specs:
        spec = dict(raw)
        step_id = spec.pop("step", None)
        if not step_id:
            raise ValueError(f"Step spec missing 'step': {raw}")

        registration = resolve_registration(step_id)
        if not registration:
            raise KeyError(f"Unknown step '{step_id}'. Known registry keys: {list(REGISTRY)}")

        name = spec.pop("name", None)
        factory_kwargs = dict(spec)
        if registration.target is not None:
            factory_kwargs["target"] = registration.target
        if name is not None:
            factory_kwargs["name"] = name
        elif registration.target is not None:
            factory_kwargs["name"] = step_id

        try:
            bound = registration.factory(**factory_kwargs)  # type: ignore[arg-type]
        except TypeError:
            if name is not None:
                tmp = registration.factory(**spec)  # type: ignore[arg-type]
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
