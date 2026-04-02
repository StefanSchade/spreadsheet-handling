"""Pipeline step factories.

Each factory binds configuration into a BoundStep closure.
Factories use lazy imports to avoid loading domain/core modules at import time.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, Dict

from .types import BoundStep, Frames

log = logging.getLogger("sheets.pipeline")


# ---------------------------------------------------------------------------
# Plugin support
# ---------------------------------------------------------------------------

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


def make_plugin_step(*, dotted: str, args: Dict[str, Any] | None = None, name: str = "plugin") -> BoundStep:
    """
    Factory for a 'plugin' step.
    dotted: dotted path to a callable
    args: optional dict of kwargs passed to the callable
    """
    fn = _resolve_callable(dotted)
    cfg = {"dotted": dotted, "args": dict(args or {})}

    def run(fr: Frames) -> Frames:
        result = fn(fr, **cfg["args"])
        return fr if result is None else result

    return BoundStep(name=name, config=cfg, fn=run)


# ---------------------------------------------------------------------------
# Built-in step factories
# ---------------------------------------------------------------------------

def make_identity_step(name: str = "identity") -> BoundStep:
    cfg: Dict[str, Any] = {}
    def run(fr: Frames) -> Frames:
        return fr
    return BoundStep(name=name, config=cfg, fn=run)


def make_validate_step(
    *,
    defaults: Dict[str, Any] | None = None,
    mode_missing_fk: str = "warn",
    mode_duplicate_ids: str = "warn",
    name: str = "validate",
) -> BoundStep:
    """Validate frames: duplicate IDs and missing FK references."""
    from ..domain.validations.fk_helpers import check_duplicate_ids, check_unresolvable_fks
    from ..domain.validations.findings import Finding, apply_severity_policy, SeverityPolicy

    cfg = {
        "defaults": dict(defaults or {}),
        "mode_missing_fk": mode_missing_fk,
        "mode_duplicate_ids": mode_duplicate_ids,
    }

    def run(fr: Frames) -> Frames:
        defs = cfg["defaults"]
        detect_fk = bool(defs.get("detect_fk", True))

        policy: SeverityPolicy = {
            "duplicate_id": cfg["mode_duplicate_ids"],
            "unresolvable_fk": cfg["mode_missing_fk"],
            "__default__": "warn",
        }

        findings: list[Finding] = check_duplicate_ids(fr, defs)
        if detect_fk:
            findings.extend(check_unresolvable_fks(fr, defs))

        apply_severity_policy(findings, policy)
        return fr

    return BoundStep(name=name, config=cfg, fn=run)


def make_apply_fks_step(
    *,
    defaults: Dict[str, Any] | None = None,
    name: str = "apply_fks",
) -> BoundStep:
    """Detect FK columns and add helper columns via core/fk pure functions."""
    from ..core.fk import (
        build_registry,
        build_id_label_maps,
        detect_fk_columns,
        apply_fk_helpers as _apply_fk_helpers,
    )

    cfg = {"defaults": dict(defaults or {})}

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
    """Remove all helper columns (starting with prefix) from all sheets."""
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


def make_check_fk_helpers_step(
    *,
    defaults: Dict[str, Any] | None = None,
    mode: str = "warn",
    name: str = "check_fk_helpers",
) -> BoundStep:
    """Run FK-helper consistency checks (pure domain validation)."""
    from ..domain.validations.fk_helpers import validate_fk_helpers
    from ..domain.validations.findings import apply_severity_policy, SeverityPolicy

    cfg = {"defaults": dict(defaults or {}), "mode": mode}

    def run(fr: Frames) -> Frames:
        findings = validate_fk_helpers(fr, cfg["defaults"])
        policy: SeverityPolicy = {"__default__": cfg["mode"]}
        apply_severity_policy(findings, policy)
        return fr

    return BoundStep(name=name, config=cfg, fn=run)


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
