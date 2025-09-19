from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, MutableMapping, Protocol, TypedDict

import logging
import pandas as pd

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
# Pipeline Runner
# ======================================================================================

def run_pipeline(frames: Frames, steps: Iterable[Step]) -> Frames:
    """
    Wendet alle Steps der Reihe nach auf die Frames-Map an.
    """
    out = frames
    for step in steps:
        log.debug("→ step: %s config=%s", getattr(step, "name", "<unnamed>"), getattr(step, "config", {}))
        out = step(out)
    return out


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


# ======================================================================================
# Registry & Config-Binding (optional, für CLI/YAML)
# ======================================================================================

class StepSpec(TypedDict, total=False):
    step: str
    name: str
    # beliebige weitere Felder abhängig vom Step, z. B.:
    defaults: Dict[str, Any]
    mode_missing_fk: str
    mode_duplicate_ids: str
    prefix: str


# Registriere hier die Step-Namen auf ihre Factory-Funktionen.
# Jede Factory nimmt nur **kwargs (aus YAML/CLI) entgegen.
REGISTRY: Dict[str, Callable[..., BoundStep]] = {
    "identity": make_identity_step,
    "validate": make_validate_step,
    "apply_fks": make_apply_fks_step,
    "drop_helpers": make_drop_helpers_step,
}


def build_steps_from_config(step_specs: Iterable[Mapping[str, Any]]) -> list[BoundStep]:
    """
    Baut eine Step-Liste aus einer Konfiguration wie:
      [
        {"step": "validate", "mode_duplicate_ids": "warn", "mode_missing_fk": "fail", "defaults": {...}},
        {"step": "apply_fks", "defaults": {...}},
        {"step": "drop_helpers", "prefix": "_"}
      ]
    """
    steps: list[BoundStep] = []
    for raw in step_specs:
        spec = dict(raw)  # defensive copy
        step_name = spec.pop("step", None)
        if not step_name:
            raise ValueError(f"Step spec missing 'step': {raw}")
        factory = REGISTRY.get(step_name)
        if not factory:
            raise KeyError(f"Unknown step '{step_name}'. Known: {list(REGISTRY)}")
        # Optionaler eigener Anzeigename
        name = spec.pop("name", step_name)
        # Viele Factories haben 'name' als kw-arg – falls nicht, ignorieren wir das via **spec
        try:
            bound = factory(name=name, **spec)  # type: ignore[arg-type]
        except TypeError:
            # Falls 'name' nicht akzeptiert wird, ohne name erneut aufrufen
            bound = factory(**spec)  # type: ignore[arg-type]
            # aber trotzdem Name setzen
            bound = BoundStep(name=name, config=bound.config, fn=bound.fn)
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

