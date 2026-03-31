from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, MutableMapping, Protocol, TypedDict

import logging
import pandas as pd

import importlib

from ..core.fk import (
    build_registry,
    build_id_label_maps,
    detect_fk_columns,
    apply_fk_helpers as _apply_fk_helpers,
    FKDef,
)
from ..core.indexing import has_level0, level0_series

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
    Validates frames: checks duplicate IDs and missing FK references.
    Delegates to core/fk pure functions (no Engine dependency).
    """
    cfg = {
        "defaults": dict(defaults or {}),
        "mode_missing_fk": mode_missing_fk,
        "mode_duplicate_ids": mode_duplicate_ids,
    }

    def _norm_id(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, float) and pd.isna(v):
            return None
        return str(v).strip()

    def run(fr: Frames) -> Frames:
        defs = cfg["defaults"]
        id_field = str(defs.get("id_field", "id"))
        detect_fk = bool(defs.get("detect_fk", True))
        helper_prefix = str(defs.get("helper_prefix", "_"))

        reg = build_registry(fr, defs)
        id_maps = build_id_label_maps(fr, reg)

        # 1) Duplicate IDs per target sheet
        dups_by_sheet: Dict[str, list] = {}
        for skey, meta in reg.items():
            sheet_name = meta["sheet_name"]
            df = fr[sheet_name]
            if not has_level0(df, id_field):
                continue
            ids = level0_series(df, id_field).astype("string")
            counts = ids.value_counts(dropna=False)
            dups = [str(idx) for idx, cnt in counts.items() if cnt > 1 and str(idx) != "nan"]
            if dups:
                dups_by_sheet[sheet_name] = dups

        m_dup = cfg["mode_duplicate_ids"]
        if dups_by_sheet:
            msg = f"duplicate IDs: {dups_by_sheet}"
            if m_dup == "fail":
                log.error(msg)
                raise ValueError(msg)
            elif m_dup == "warn":
                log.warning(msg)

        # 2) Missing FK references
        m_fk = cfg["mode_missing_fk"]
        missing_by_sheet: Dict[str, list] = {}
        if detect_fk:
            for sheet_name, df in fr.items():
                fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
                for fk in fk_defs:
                    col = fk.fk_column
                    target_key = fk.target_sheet_key
                    if col not in df.columns:
                        continue
                    vals = level0_series(df, col).astype("string")
                    target_map = id_maps.get(target_key, {})
                    missing_vals = sorted(
                        {str(v) for v in vals.dropna().unique() if _norm_id(v) not in target_map}
                    )
                    if missing_vals:
                        missing_by_sheet.setdefault(sheet_name, []).append(
                            {"column": col, "missing_values": missing_vals}
                        )

        if missing_by_sheet:
            if m_fk == "fail":
                raise ValueError(f"missing FK references: {missing_by_sheet}")
            elif m_fk == "warn":
                compact = {
                    s: {iss["column"]: iss["missing_values"] for iss in issues}
                    for s, issues in missing_by_sheet.items()
                }
                log.warning("missing FK references: %s", compact)

        return fr

    return BoundStep(name=name, config=cfg, fn=run)


def make_apply_fks_step(
    *,
    defaults: Dict[str, Any] | None = None,
    name: str = "apply_fks",
) -> BoundStep:
    """
    Detects FK columns and adds helper columns via core/fk pure functions.
    """
    cfg = {
        "defaults": dict(defaults or {}),
    }

    def run(fr: Frames) -> Frames:
        defs = cfg["defaults"]
        if not bool(defs.get("detect_fk", True)):
            return fr

        reg = build_registry(fr, defs)
        id_maps = build_id_label_maps(fr, reg)
        levels = int(defs.get("levels", 3))
        helper_prefix = str(defs.get("helper_prefix", "_"))

        out: Frames = {}
        for sheet_name, df in fr.items():
            fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix)
            out[sheet_name] = _apply_fk_helpers(
                df, fk_defs, id_maps, levels, helper_prefix=helper_prefix
            )
        return out

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


def make_unflatten_headers_step(*, sheet: str | None = None, sep: str = ".", name: str = "unflatten_headers") -> BoundStep:
    from ..domain.transformations.helpers import unflatten_headers as _unflatten
    cfg = {"sheet": sheet, "sep": sep}
    def run(fr: Frames) -> Frames:
        return _unflatten(sheet, sep=sep)(fr)
    return BoundStep(name=name, config=cfg, fn=run)

def make_reorder_helpers_step(*, sheet: str | None = None, helper_prefix: str = "_", name: str = "reorder_helpers") -> BoundStep:
    from ..domain.transformations.helpers import reorder_helpers_next_to_fk as _reorder
    cfg = {"sheet": sheet, "helper_prefix": helper_prefix}
    def run(fr: Frames) -> Frames:
        return _reorder(sheet, helper_prefix=helper_prefix)(fr)
    return BoundStep(name=name, config=cfg, fn=run)


# in pipeline/pipeline.py
def make_add_validations_step(*, rules: list[dict], name: str = "add_validations") -> BoundStep:
    from ..domain.validations.validate_columns import add_validations as _impl

    cfg = {"rules": rules}
    def run(fr: Frames) -> Frames:
        return _impl(fr, rules=cfg["rules"])
    return BoundStep(name=name, config=cfg, fn=run)


def make_bootstrap_meta_step(
    *,
    profile_defaults: Dict[str, Any] | None = None,
    cli_overrides: Dict[str, Any] | None = None,
    name: str = "bootstrap_meta",
) -> BoundStep:
    from ..domain.meta_bootstrap import bootstrap_meta as _impl

    cfg = {"profile_defaults": profile_defaults, "cli_overrides": cli_overrides}
    def run(fr: Frames) -> Frames:
        return _impl(fr, profile_defaults=cfg["profile_defaults"], cli_overrides=cfg["cli_overrides"])
    return BoundStep(name=name, config=cfg, fn=run)


def make_apply_overrides_step(
    *,
    overrides_path: str | None = None,
    overrides: Dict[str, Any] | None = None,
    name: str = "apply_overrides",
) -> BoundStep:
    from ..domain.yaml_overrides import load_overrides, apply_overrides as _apply

    cfg = {"overrides_path": overrides_path, "overrides": overrides}
    def run(fr: Frames) -> Frames:
        ov = cfg["overrides"]
        if ov is None and cfg["overrides_path"]:
            ov = load_overrides(cfg["overrides_path"])
        if ov:
            return _apply(fr, ov)
        return fr
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
    "plugin":           make_plugin_step,
    "flatten_headers":  make_flatten_headers_step,
    "unflatten_headers": make_unflatten_headers_step,
    "reorder_helpers":  make_reorder_helpers_step,
    "add_validations":  make_add_validations_step,
    "bootstrap_meta":   make_bootstrap_meta_step,
    "apply_overrides":  make_apply_overrides_step,
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
            # Factory might not accept 'name' - retry without it and wrap
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

