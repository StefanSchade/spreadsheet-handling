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


def _resolve_target(target: str | Callable[..., Any]) -> Callable[..., Any]:
    return _resolve_callable(target) if isinstance(target, str) else target


def _target_label(target: str | Callable[..., Any]) -> str:
    if isinstance(target, str):
        return target
    module = getattr(target, "__module__", "")
    qualname = getattr(target, "__qualname__", getattr(target, "__name__", repr(target)))
    return f"{module}:{qualname}" if module else qualname


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


def make_builder_target_step(
    *,
    target: str | Callable[..., Any],
    name: str,
    **kwargs: Any,
) -> BoundStep:
    """
    Generic binder for builder-style callables: ``(...config) -> Step``.
    """
    fn = _resolve_target(target)
    cfg = {"target": _target_label(target), **dict(kwargs)}

    def run(fr: Frames) -> Frames:
        step = fn(**kwargs)
        if not callable(step):
            raise TypeError(f"Builder target did not return a step: {cfg['target']}")
        result = step(fr)
        return fr if result is None else result

    return BoundStep(name=name, config=cfg, fn=run)


def make_frames_target_step(
    *,
    target: str | Callable[..., Any],
    name: str,
    **kwargs: Any,
) -> BoundStep:
    """
    Generic binder for frames-first callables: ``(frames, **config) -> Frames``.
    """
    fn = _resolve_target(target)
    cfg = {"target": _target_label(target), **dict(kwargs)}

    def run(fr: Frames) -> Frames:
        result = fn(fr, **kwargs)
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
    name: str = "add_fk_helpers",
) -> BoundStep:
    """Detect FK columns and add helper columns.

    Delegates to ``domain.transformations.fk_helpers.enrich_helpers``.
    """
    from ..domain.transformations.fk_helpers import enrich_helpers

    cfg = {"defaults": dict(defaults or {})}

    def run(fr: Frames) -> Frames:
        return enrich_helpers(fr, cfg["defaults"])

    return BoundStep(name=name, config=cfg, fn=run)


def make_drop_helpers_step(
    *,
    prefix: str = "_",
    name: str = "remove_fk_helpers",
) -> BoundStep:
    """Remove all helper columns (starting with prefix) from all sheets.

    Delegates to ``domain.transformations.fk_helpers.drop_helpers``.
    """
    from ..domain.transformations.fk_helpers import drop_helpers

    cfg = {"prefix": prefix}

    def run(fr: Frames) -> Frames:
        return drop_helpers(fr, prefix=cfg["prefix"])

    return BoundStep(name=name, config=cfg, fn=run)


def make_flatten_headers_step(*, sheet: str | None = None, mode: str = "first_nonempty", sep: str = "", name: str = "flatten_headers") -> BoundStep:
    return make_builder_target_step(
        target="spreadsheet_handling.domain.transformations.helpers:flatten_headers",
        name=name,
        sheet=sheet,
        mode=mode,
        sep=sep,
    )


def make_unflatten_headers_step(*, sheet: str | None = None, sep: str = ".", name: str = "unflatten_headers") -> BoundStep:
    return make_builder_target_step(
        target="spreadsheet_handling.domain.transformations.helpers:unflatten_headers",
        name=name,
        sheet=sheet,
        sep=sep,
    )


def make_reorder_helpers_step(*, sheet: str | None = None, helper_prefix: str = "_", name: str = "reorder_fk_helpers") -> BoundStep:
    return make_builder_target_step(
        target="spreadsheet_handling.domain.transformations.helpers:reorder_helpers_next_to_fk",
        name=name,
        sheet=sheet,
        helper_prefix=helper_prefix,
    )


def make_check_fk_helpers_step(
    *,
    defaults: Dict[str, Any] | None = None,
    mode: str = "warn",
    name: str = "validate_fk_helpers",
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
    return make_frames_target_step(
        target="spreadsheet_handling.domain.validations.validate_columns:add_validations",
        name=name,
        rules=rules,
    )


def make_bootstrap_meta_step(
    *,
    profile_defaults: Dict[str, Any] | None = None,
    cli_overrides: Dict[str, Any] | None = None,
    name: str = "bootstrap_meta",
) -> BoundStep:
    return make_frames_target_step(
        target="spreadsheet_handling.domain.meta_bootstrap:bootstrap_meta",
        name=name,
        profile_defaults=profile_defaults,
        cli_overrides=cli_overrides,
    )


def make_apply_overrides_step(
    *,
    overrides_path: str | None = None,
    overrides: Dict[str, Any] | None = None,
    name: str = "apply_overrides",
) -> BoundStep:
    return make_frames_target_step(
        target="spreadsheet_handling.domain.yaml_overrides:load_and_apply_overrides",
        name=name,
        overrides_path=overrides_path,
        overrides=overrides,
    )
