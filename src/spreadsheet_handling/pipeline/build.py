"""Build bound pipeline steps from canonical step-based configuration."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .registry import REGISTRY, resolve_registration
from .types import BoundStep


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
    steps: list[BoundStep] = []
    for raw in step_specs:
        spec = dict(raw)
        step_id = spec.pop("step", None)
        if not step_id:
            raise ValueError(f"Step spec missing 'step': {raw}")
        _ensure_string_parameter_keys(step_id, spec)

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


def _ensure_string_parameter_keys(step_id: str, spec: Mapping[Any, Any]) -> None:
    non_string_keys = [key for key in spec if not isinstance(key, str)]
    if not non_string_keys:
        return

    hint = ""
    if step_id == "add_lookup_helpers" and True in non_string_keys:
        hint = (
            " This commonly means an unquoted YAML 1.1 boolean-like key such "
            "as `on:` was parsed as True; prefer `key:`/`keys:` or quote the "
            'legacy spelling as `"on":`.'
        )
    raise ValueError(
        f"Step {step_id!r} contains non-string parameter key(s) {non_string_keys!r}." f"{hint}"
    )


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
