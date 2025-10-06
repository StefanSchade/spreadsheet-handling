from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, MutableMapping, Protocol, TypedDict

import logging
import pandas as pd

import importlib

# Wir nutzen die bestehende Engine weiter (keine Logik-Duplikate)
from ..engine.orchestrator import Engine

log = logging.getLogger("sheets.pipeline")

# ======================================================================================
# Typen
# ======================================================================================

Frames = Dict[str, pd.DataFrame]  # zentrale Payload: Mappe = {sheet_name -> DataFrame}


class Step(Protocol):
    """
    A Step is a callable object, that transforms a map of frames (representing the set of tables in one spreadsheet)
    into another map of frames.
    """
    name: str
    config: Dict[str, Any]

    def __call__(self, frames: Frames) -> Frames: ...


@dataclass(frozen=True)
class BoundStep:
    """
    Bound step (Name + Config + Callable).
    - name/config sind für Logging, Debugging, Introspection nützlich.
    - fn kapselt die eigentliche Logik (oft als Closure aus einer Factory).
    """
    name: str
    config: Dict[str, Any]
    fn: Callable[[Frames], Frames]

    def __call__(self, frames: Frames) -> Frames:
        return self.fn(frames)

# ======================================================================================
# Pipeline Runner (unchanged)
# ======================================================================================

def run_pipeline(frames: Frames, steps: Iterable[Step]) -> Frames:
    out = frames
    for step in steps:
        log.debug("→ step: %s config=%s", getattr(step, "name", "<unnamed>"), getattr(step, "config", {}))
        out = step(out)
    return out

# ======================================================================================
# Plugin step support (factory-based)
# ======================================================================================

import importlib

def _resolve_callable(dotted: str) -> Callable[..., Any]:
    """
    Import a dotted callable like 'package.module:function' or 'package.module.attr'.
    Accepts both 'pkg.mod:func' and 'pkg.mod.func' styles.
    """
    if ":" in dotted:
        mod_path, attr = dotted.split(":", 1)
    else:
        mod_path, attr = dotted.rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    fn = getattr(mod, attr)
    if not callable(fn):
        raise TypeError(f"Not callable: {dotted}")
    return fn

def make_plugin_step(*, func: str, args: Dict[str, Any] | None = None, name: str = "plugin") -> BoundStep:
    """
    Factory for a 'plugin' step.
    - func: dotted path to a callable (e.g. 'plugins.extractions.foo:run' or 'plugins.extractions.foo.run')
    - args: optional dict of kwargs passed to the callable
    The callable should accept (frames: dict[str, DataFrame], **kwargs) and either return a
    frames dict or None (None keeps the incoming frames unchanged).
    """
    fn = _resolve_callable(func)
    cfg = {"func": func, "args": dict(args or {})}

    def run(fr: Frames) -> Frames:
        result = fn(fr, **cfg["args"])
        return fr if result is None else result

    return BoundStep(name=name, config=cfg, fn=run)

# ======================================================================================
# Step-Factories (Closures, die die Konfiguration binden)
# ======================================================================================

def make_identity_step(name: str = "identity") -> BoundStep:
    """
    No-Op (praktisch zum Testen/Debuggen).
    """
    cfg: Dict[str, Any] = {}
    def run(fr: Frames) -> Frames:
        return fr
    return BoundStep(name=name, config=cfg, fn=run)


def make_validate_step(
    *,
    defaults: Dict[str, Any] | None = None,
    mode_missing_fk: str = "warn",      # 'ignore' | 'warn' | 'fail'
    mode_duplicate_ids: str = "warn",   # 'ignore' | 'warn' | 'fail'
    name: str = "validate",
) -> BoundStep:
    """
    Wrappt Engine.validate zu einem Pipeline-Step (keine Behavior-Änderung).
    """
    cfg = {
        "defaults": dict(defaults or {}),
        "mode_missing_fk": mode_missing_fk,
        "mode_duplicate_ids": mode_duplicate_ids,
    }

    def run(fr: Frames) -> Frames:
        eng = Engine(defaults=cfg["defaults"])
        # validate liefert Report; Frames bleiben (gewollt) unverändert
        eng.validate(
            fr,
            mode_missing_fk=cfg["mode_missing_fk"],
            mode_duplicate_ids=cfg["mode_duplicate_ids"],
        )
        return fr

    return BoundStep(name=name, config=cfg, fn=run)


def make_apply_fks_step(
    *,
    defaults: Dict[str, Any] | None = None,
    name: str = "apply_fks",
) -> BoundStep:
    """
    Wrappt Engine.apply_fks (fügt Helper-Spalten hinzu).
    """
    cfg = {
        "defaults": dict(defaults or {}),
    }

    def run(fr: Frames) -> Frames:
        eng = Engine(defaults=cfg["defaults"])
        return eng.apply_fks(fr)

    return BoundStep(name=name, config=cfg, fn=run)


def make_drop_helpers_step(
    *,
    prefix: str = "_",
    name: str = "drop_helpers",
) -> BoundStep:
    """
    Entfernt alle Helper-Spalten (starten mit 'prefix') aus allen Sheets.
    """
    cfg = {"prefix": prefix}

    def run(fr: Frames) -> Frames:
        out: Frames = {}
        for sheet, df in fr.items():
            cols = [c for c in df.columns if not str(c).startswith(cfg["prefix"])]
            out[sheet] = df.loc[:, cols]
        return out

    return BoundStep(name=name, config=cfg, fn=run)

def make_flatten_headers_step(*, sheet: str | None = None, mode: str = "first_nonempty", sep: str = "", name: str = "flatten_headers") -> BoundStep:
    from ..domain.transformations.helpers import flatten_headers as _flatten
    cfg = {"sheet": sheet, "mode": mode, "sep": sep}
    def run(fr: Frames) -> Frames:
        return _flatten(sheet, mode=mode, sep=sep)(fr)
    return BoundStep(name=name, config=cfg, fn=run)

def make_reorder_helpers_step(*, sheet: str | None = None, helper_prefix: str = "_", name: str = "reorder_helpers") -> BoundStep:
    from ..domain.transformations.helpers import reorder_helpers_next_to_fk as _reorder
    cfg = {"sheet": sheet, "helper_prefix": helper_prefix}
    def run(fr: Frames) -> Frames:
        return _reorder(sheet, helper_prefix=helper_prefix)(fr)
    return BoundStep(name=name, config=cfg, fn=run)


# ======================================================================================
# Registry & Config-Binding (for CLI/YAML)
# ======================================================================================

class StepSpec(TypedDict, total=False):
    step: str
    name: str
    defaults: Dict[str, Any]
    mode_missing_fk: str
    mode_duplicate_ids: str
    prefix: str
    # plugin-specific
    func: str
    args: Dict[str, Any]

# Registry & Config-Binding
REGISTRY: Dict[str, Callable[..., BoundStep]] = {
    "identity":         make_identity_step,
    "validate":         make_validate_step,
    "apply_fks":        make_apply_fks_step,
    "drop_helpers":     make_drop_helpers_step,
    "plugin":           make_plugin_step,        # schon drin
    "flatten_headers":  make_flatten_headers_step,   # NEU
    "reorder_helpers":  make_reorder_helpers_step,   # NEU
}

def build_steps_from_config(step_specs: Iterable[Mapping[str, Any]]) -> list[BoundStep]:
    """
    Build steps from a config list like:
      - step: validate
        mode_duplicate_ids: warn
        ...
      - step: my_project.steps:make_extract_subset_step
        table: Orders
        columns: [id, date]
    Supported 'step' values:
      1) registry key (see REGISTRY)
      2) dotted path in the form '<module>:<factory_function>'
    """
    import importlib

    def resolve_factory(step_id: str) -> Callable[..., BoundStep] | None:
        # 1) registry
        factory = REGISTRY.get(step_id)
        if factory:
            return factory
        # 2) dotted path "<module>:<factory>"
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
        spec = dict(raw)  # defensive copy
        step_id = spec.pop("step", None)
        if not step_id:
            raise ValueError(f"Step spec missing 'step': {raw}")

        factory = resolve_factory(step_id)
        if not factory:
            raise KeyError(f"Unknown step '{step_id}'. Known registry keys: {list(REGISTRY)}")

        # optional explicit display name
        name = spec.pop("name", None)

        try:
            bound = factory(name=name, **spec) if name is not None else factory(**spec)  # type: ignore[arg-type]
        except TypeError:
            # Factory might not accept 'name' – retry without it and wrap
            if name is not None:
                tmp = factory(**spec)  # type: ignore[arg-type]
                bound = BoundStep(name=name, config=tmp.config, fn=tmp.fn)
            else:
                raise
        steps.append(bound)
    return steps

# --- YAML convenience (optional) ------------------------------------------------
try:
    import yaml  # from pyyaml
except Exception:  # pragma: no cover
    yaml = None

def build_steps_from_yaml(path: str) -> list[BoundStep]:
    """
    Load a pipeline spec from YAML (expects top-level key 'pipeline': [ ... ]).
    Example YAML:
      pipeline:
        - step: validate
          mode_duplicate_ids: warn
          mode_missing_fk: warn
          defaults:
            id_field: id
            label_field: name
            detect_fk: true
            helper_prefix: "_"
        - step: apply_fks
          defaults:
            id_field: id
            label_field: name
        - step: drop_helpers
          prefix: "_"
    """
    if yaml is None:
        raise RuntimeError("PyYAML not installed; install with [dev] or add pyyaml to deps.")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    specs = cfg.get("pipeline")
    if not isinstance(specs, list):
        raise ValueError(f"YAML missing 'pipeline' list: {path}")
    return build_steps_from_config(specs)

# ======================================================================================
# Beispiel (nur Doku/Kommentar)
# ======================================================================================

"""
# Beispielhafte Verwendung aus der App/CLI:

defaults = {"id_field": "id", "label_field": "name", "detect_fk": True, "helper_prefix": "_"}

steps = [
    make_validate_step(defaults=defaults, mode_duplicate_ids="warn", mode_missing_fk="warn"),
    make_apply_fks_step(defaults=defaults),
    make_drop_helpers_step(prefix=defaults.get("helper_prefix", "_")),
]

result_frames = run_pipeline(input_frames, steps)

# Oder aus YAML:
# pipeline:
#   - step: validate
#     mode_duplicate_ids: warn
#     mode_missing_fk: warn
#     defaults:
#       id_field: id
#       label_field: name
#       detect_fk: true
#       helper_prefix: "_"
#   - step: apply_fks
#     defaults:
#       id_field: id
#       label_field: name
#   - step: drop_helpers
#     prefix: "_"
#
# steps = build_steps_from_config(config["pipeline"])
# result_frames = run_pipeline(input_frames, steps)
"""

