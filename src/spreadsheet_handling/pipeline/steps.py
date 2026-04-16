"""Pipeline step factories.

Each factory binds configuration into a BoundStep closure.
Factories use lazy imports to avoid loading domain/core modules at import time.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, Dict

from ..frame_keys import copy_reserved_frames, iter_data_frames
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
    name: str = "apply_fks",
) -> BoundStep:
    """Detect FK columns and add helper columns via core/fk pure functions."""
    from ..core.fk import (
        build_registry,
        build_id_value_maps,
        detect_fk_columns,
        apply_fk_helpers as _apply_fk_helpers,
    )

    cfg = {"defaults": dict(defaults or {})}

    def run(fr: Frames) -> Frames:
        defs = cfg["defaults"]
        if not bool(defs.get("detect_fk", True)):
            return fr

        reg = build_registry(fr, defs)
        levels = int(defs.get("levels", 3))
        helper_prefix = str(defs.get("helper_prefix", "_"))
        fk_defs_by_sheet: dict[str, Any] = {}
        fields_by_target: dict[str, list[str]] = {}

        for sheet_name, df in iter_data_frames(fr):
            fk_defs = detect_fk_columns(df, reg, helper_prefix=helper_prefix, defaults=defs)
            fk_defs_by_sheet[sheet_name] = fk_defs
            for fk in fk_defs:
                fields_by_target.setdefault(fk.target_sheet_key, [])
                if fk.value_field not in fields_by_target[fk.target_sheet_key]:
                    fields_by_target[fk.target_sheet_key].append(fk.value_field)

        id_maps = build_id_value_maps(fr, reg, fields_by_sheet=fields_by_target)

        out: dict[str, Any] = {}
        copy_reserved_frames(fr, out)
        for sheet_name, df in iter_data_frames(fr):
            fk_defs = fk_defs_by_sheet[sheet_name]
            out[sheet_name] = _apply_fk_helpers(
                df, fk_defs, id_maps, levels, helper_prefix=helper_prefix
            )

        # --- FTR-FK-HELPER-PROVENANCE-CLEANUP: persist derived helper provenance ---
        has_any_fks = any(bool(fds) for fds in fk_defs_by_sheet.values())
        existing_meta = out.get("_meta")
        has_existing_prov = bool(
            ((existing_meta or {}).get("derived") or {}).get("sheets")
        )
        if has_any_fks or has_existing_prov or existing_meta is not None:
            meta: dict[str, Any] = dict(existing_meta or {})
            derived: dict[str, Any] = meta.setdefault("derived", {})
            derived_sheets: dict[str, Any] = derived.setdefault("sheets", {})
            for sheet_name, fk_defs in fk_defs_by_sheet.items():
                if fk_defs:
                    entries = [
                        {
                            "column": fk.helper_column,
                            "fk_column": fk.fk_column,
                            "target": fk.target_sheet_key,
                            "value_field": fk.value_field,
                        }
                        for fk in fk_defs
                    ]
                    # Key-selective merge: only replace helper_columns, preserve
                    # other derived keys that may exist for this sheet.
                    derived_sheets.setdefault(sheet_name, {})["helper_columns"] = entries
                else:
                    # Remove stale provenance for sheets without current FK defs.
                    if sheet_name in derived_sheets:
                        derived_sheets[sheet_name].pop("helper_columns", None)
                        if not derived_sheets[sheet_name]:
                            del derived_sheets[sheet_name]
            # Also clean provenance for sheets no longer in frames at all.
            current_sheets = set(fk_defs_by_sheet)
            for stale in [k for k in derived_sheets if k not in current_sheets]:
                derived_sheets[stale].pop("helper_columns", None)
                if not derived_sheets[stale]:
                    del derived_sheets[stale]
            # Prune empty derived namespace.
            if not derived_sheets:
                derived.pop("sheets", None)
            if not derived:
                meta.pop("derived", None)
            out["_meta"] = meta

        return out  # type: ignore[return-value]

    return BoundStep(name=name, config=cfg, fn=run)


def make_drop_helpers_step(
    *,
    prefix: str = "_",
    name: str = "drop_helpers",
) -> BoundStep:
    """Remove all helper columns (starting with prefix) from all sheets.

    When derived helper provenance exists in ``_meta["derived"]["sheets"]``,
    columns listed there are removed first and the provenance entries are
    cleaned up.  Prefix-based removal remains as backward-compatible fallback
    for frames without provenance metadata.
    """
    cfg = {"prefix": prefix}

    def _visible_label(col: Any) -> str:
        if isinstance(col, tuple):
            for part in col:
                label = str(part)
                if label:
                    return label
            return ""
        return str(col)

    def run(fr: Frames) -> Frames:
        out: dict[str, Any] = {}
        copy_reserved_frames(fr, out)
        meta: dict[str, Any] = dict(out.get("_meta") or {})
        derived_sheets: dict[str, Any] = (meta.get("derived") or {}).get("sheets") or {}

        for sheet, df in iter_data_frames(fr):
            sheet_prov = (derived_sheets.get(sheet) or {}).get("helper_columns")
            if sheet_prov:
                # Metadata-backed removal: drop exactly the columns listed in provenance
                prov_cols = {entry["column"] for entry in sheet_prov}
                cols = [
                    c for c in df.columns
                    if _visible_label(c) not in prov_cols
                ]
                out[sheet] = df.loc[:, cols]
            else:
                # Prefix-based fallback
                cols = [c for c in df.columns if not _visible_label(c).startswith(cfg["prefix"])]
                out[sheet] = df.loc[:, cols]

        # Clean up helper provenance after removal
        if derived_sheets:
            for sheet_name in list(derived_sheets.keys()):
                if "helper_columns" in (derived_sheets.get(sheet_name) or {}):
                    derived_sheets[sheet_name].pop("helper_columns")
                    if not derived_sheets[sheet_name]:
                        del derived_sheets[sheet_name]
            # Write cleaned meta back
            derived = meta.get("derived") or {}
            if derived.get("sheets") is not None and not derived["sheets"]:
                del derived["sheets"]
            if not derived:
                meta.pop("derived", None)
            out["_meta"] = meta

        return out  # type: ignore[return-value]

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


def make_reorder_helpers_step(*, sheet: str | None = None, helper_prefix: str = "_", name: str = "reorder_helpers") -> BoundStep:
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
