"""Pipeline step factories.

Each factory binds configuration into a BoundStep closure.
Factories use lazy imports to avoid loading domain/core modules at import time.

Every factory here exposes ``BoundStep.config`` as a read-only
``MappingProxyType`` view built from the same values its execution reads, so
a step built through this module cannot have its descriptive config
reassigned after binding (closing the divergence between "what the
certificate says" and "what actually executes" -- see
``pipeline.execution_state`` and FTR-TRUSTED-INGRESS-P4A section 18).

``make_frames_target_step`` -- the shared binder for every Phase-E E4
reviewed target (``add_lookup_helpers``, ``contract_grouped_xref``,
``reconstruct_grouped_matrix``, ``expand_grouped_xref``,
``write_artifact_manifest``) -- additionally builds its ``BoundStep.fn`` as a
``types.BoundFramesTargetCall`` rather than an anonymous closure: that
class's ``__call__`` mechanically executes exactly
``self.target(frames, **self.kwargs)``, so E4's classifiers can prove which
callable and configuration a step actually runs by inspecting ``step.fn``
itself (``type(step.fn) is BoundFramesTargetCall`` and ``step.fn.target is
<the exact reviewed callable>``), not by trusting a separately-suppliable
label or marker. See ``BoundFramesTargetCall``'s docstring in
``pipeline/types.py`` and ``pipeline.execution_state.bound_configuration``.
"""
from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any, Callable, Dict

from .dotted_paths import resolve_configuration_callable
from .types import BoundFramesTargetCall, BoundStep, Frames

log = logging.getLogger("sheets.pipeline")


# ---------------------------------------------------------------------------
# Plugin support
# ---------------------------------------------------------------------------

def _resolve_target(target: str | Callable[..., Any]) -> Callable[..., Any]:
    return resolve_configuration_callable(target) if isinstance(target, str) else target


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
    fn = resolve_configuration_callable(dotted)
    cfg = {"dotted": dotted, "args": dict(args or {})}

    def run(fr: Frames) -> Frames:
        result = fn(fr, **cfg["args"])
        return fr if result is None else result

    return BoundStep(name=name, config=MappingProxyType(cfg), fn=run)


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

    return BoundStep(name=name, config=MappingProxyType(cfg), fn=run)


def make_frames_target_step(
    *,
    target: str | Callable[..., Any],
    name: str,
    **kwargs: Any,
) -> BoundStep:
    """
    Generic binder for frames-first callables: ``(frames, **config) -> Frames``.

    ``fn`` is a ``BoundFramesTargetCall`` wrapping the resolved ``target``
    and an immutable view of ``kwargs``, not an anonymous closure -- see the
    module docstring and that class's own docstring for why this is the E4
    authenticity seam.
    """
    fn = _resolve_target(target)
    effective_kwargs = MappingProxyType(dict(kwargs))
    cfg = MappingProxyType({"target": _target_label(target), **effective_kwargs})
    call = BoundFramesTargetCall(fn, effective_kwargs)
    return BoundStep(name=name, config=cfg, fn=call)


# ---------------------------------------------------------------------------
# Built-in step factories
# ---------------------------------------------------------------------------

def make_identity_step(name: str = "identity") -> BoundStep:
    cfg: Dict[str, Any] = {}
    def run(fr: Frames) -> Frames:
        return fr
    return BoundStep(name=name, config=MappingProxyType(cfg), fn=run)


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

    return BoundStep(name=name, config=MappingProxyType(cfg), fn=run)


def make_apply_fks_step(
    *,
    defaults: Dict[str, Any] | None = None,
    name: str = "add_fk_helpers",
) -> BoundStep:
    """Add FK helper columns from the v2 relation policy.

    Reads ``_meta.helper_policies.fk.relations`` (v2, required); relation
    identity comes from policy — no convention-based FK inference is performed.
    Missing policy raises a clear error naming the producer step
    (``configure_fk_helpers`` or ``infer_fk_relations``).
    Delegates to ``domain.transformations.fk_helpers.enrich_helpers``.
    """
    from ..domain.transformations.fk_helpers import enrich_helpers

    cfg = {"defaults": dict(defaults or {})}

    def run(fr: Frames) -> Frames:
        return enrich_helpers(fr, cfg["defaults"])

    return BoundStep(name=name, config=MappingProxyType(cfg), fn=run)


def make_drop_helpers_step(
    *,
    prefix: str = "_",
    name: str = "remove_fk_helpers",
) -> BoundStep:
    """Remove FK helper columns identified by provenance or v2 policy.

    Primary source: derived helper provenance at
    ``_meta.derived.sheets.*.helper_columns``. Fallback: v2 relation policy.
    Missing both raises a clear error naming the producer step. The ``prefix``
    parameter is retained for step-binding compatibility only and no longer
    drives cleanup behavior.
    Delegates to ``domain.transformations.fk_helpers.drop_helpers``.
    """
    from ..domain.transformations.fk_helpers import drop_helpers

    cfg = {"prefix": prefix}

    def run(fr: Frames) -> Frames:
        return drop_helpers(fr, prefix=cfg["prefix"])

    return BoundStep(name=name, config=MappingProxyType(cfg), fn=run)


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

    return BoundStep(name=name, config=MappingProxyType(cfg), fn=run)


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
