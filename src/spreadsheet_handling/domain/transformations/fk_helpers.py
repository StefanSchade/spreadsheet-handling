"""FK-helper domain transformations: enrichment and cleanup.

Extracted from pipeline.steps (FTR-FK-HELPER-DOMAIN-EXTRACTION).
Pipeline step factories delegate here; this module owns the full
FK-helper lifecycle: resolution, enrichment, provenance, and cleanup.
"""
from __future__ import annotations

from typing import Any

from ...core.fk import (
    FKDef,
    build_registry,
    build_id_value_maps,
    detect_fk_columns,
    normalize_sheet_key,
    apply_fk_helpers as _apply_fk_helpers,
)
from ...frame_keys import copy_reserved_frames, iter_data_frames
from ...rendering.formulas import lookup_formula

Frames = dict[str, Any]

_VALUE_HELPER_MODES = {"value", "values"}
_FORMULA_HELPER_MODES = {"formula", "formulas"}


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def enrich_helpers(frames: Frames, defaults: dict[str, Any]) -> Frames:
    """Detect FK columns, add helper columns, and write derived provenance.

    This is the domain entry-point called by the ``apply_fks`` pipeline step.
    It orchestrates core.fk utilities and owns the ``_meta`` provenance
    contract for helper columns.
    """
    if not bool(defaults.get("detect_fk", True)):
        return frames

    execution_defaults, fk_policies = _defaults_with_fk_policies(frames, defaults)

    reg = build_registry(frames, execution_defaults)
    levels = int(execution_defaults.get("levels", 3))
    helper_prefix = str(execution_defaults.get("helper_prefix", "_"))
    helper_value_mode = _helper_value_mode(execution_defaults)
    helper_value_provider = (
        _lookup_formula_provider(reg)
        if helper_value_mode in _FORMULA_HELPER_MODES
        else None
    )
    fk_defs_by_sheet: dict[str, Any] = {}
    fields_by_target: dict[str, list[str]] = {}

    for sheet_name, df in iter_data_frames(frames):
        fk_defs = detect_fk_columns(
            df,
            reg,
            helper_prefix=helper_prefix,
            defaults=execution_defaults,
        )
        fk_defs_by_sheet[sheet_name] = fk_defs
        for fk in fk_defs:
            fields_by_target.setdefault(fk.target_sheet_key, [])
            if fk.value_field not in fields_by_target[fk.target_sheet_key]:
                fields_by_target[fk.target_sheet_key].append(fk.value_field)

    _validate_fk_policy_usage(fk_defs_by_sheet, fk_policies)

    id_maps = build_id_value_maps(frames, reg, fields_by_sheet=fields_by_target)

    out: dict[str, Any] = {}
    copy_reserved_frames(frames, out)
    for sheet_name, df in iter_data_frames(frames):
        fk_defs = fk_defs_by_sheet[sheet_name]
        out[sheet_name] = _apply_fk_helpers(
            df,
            fk_defs,
            id_maps,
            levels,
            helper_prefix=helper_prefix,
            helper_value_provider=helper_value_provider,
        )

    _write_helper_provenance(out, fk_defs_by_sheet)
    return out


def _helper_value_mode(defaults: dict[str, Any]) -> str:
    mode = str(defaults.get("helper_value_mode", "values")).lower()
    if mode not in _VALUE_HELPER_MODES and mode not in _FORMULA_HELPER_MODES:
        raise ValueError(
            "helper_value_mode must be one of "
            f"{sorted(_VALUE_HELPER_MODES | _FORMULA_HELPER_MODES)}"
        )
    return mode


def _lookup_formula_provider(registry: dict[str, dict[str, Any]]):
    def provider(fk: FKDef, raw_ids: list[Any]) -> list[Any]:
        target = registry.get(fk.target_sheet_key) or {}
        lookup_sheet = str(target.get("sheet_name") or fk.target_sheet_key)
        formula = lookup_formula(
            source_key_column=fk.fk_column,
            lookup_sheet=lookup_sheet,
            lookup_key_column=fk.id_field,
            lookup_value_column=fk.value_field,
            missing="",
        )
        return [formula for _ in raw_ids]

    return provider


def _defaults_with_fk_policies(
    frames: Frames,
    defaults: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    policies = _fk_policies(frames)
    if not policies:
        return defaults, {}

    execution_defaults = dict(defaults)
    by_target = dict(execution_defaults.get("helper_fields_by_target") or {})
    by_fk = dict(execution_defaults.get("helper_fields_by_fk") or {})
    id_by_target = dict(execution_defaults.get("id_field_by_target") or {})
    label_by_target = dict(execution_defaults.get("label_field_by_target") or {})
    inline_helper_prefix = (
        str(defaults["helper_prefix"])
        if "helper_prefix" in defaults
        else None
    )
    resolved_helper_prefix: str | None = None

    for target_key, policy in policies.items():
        target_sheet = str(policy.get("target_sheet") or target_key)
        policy_key = str(policy.get("key") or execution_defaults.get("id_field", "id"))
        default_helpers = _list_value(policy.get("default_helpers"))
        policy_allowed = (
            _list_value(policy.get("allowed_helpers"))
            if "allowed_helpers" in policy
            else None
        )
        policy_prefix = str(policy.get("helper_prefix", inline_helper_prefix or "_"))

        if inline_helper_prefix is not None and inline_helper_prefix != policy_prefix:
            raise ValueError(
                f"Inline helper_prefix {inline_helper_prefix!r} conflicts with "
                f"resolved FK helper policy for target {target_key!r}: {policy_prefix!r}"
            )
        if resolved_helper_prefix is None:
            resolved_helper_prefix = policy_prefix
        elif resolved_helper_prefix != policy_prefix:
            raise ValueError(
                "Resolved FK helper policies define multiple helper_prefix values "
                f"({resolved_helper_prefix!r}, {policy_prefix!r}); one add_fk_helpers "
                "execution supports a single helper_prefix"
            )

        if policy_allowed is not None:
            disallowed_defaults = [
                field for field in default_helpers
                if field not in policy_allowed
            ]
            if disallowed_defaults:
                raise ValueError(
                    f"default_helpers {disallowed_defaults!r} must be included in "
                    f"allowed_helpers for FK target {target_key!r}: {policy_allowed!r}"
                )

        _merge_scalar_target_default(
            id_by_target,
            target_key=target_key,
            target_sheet=target_sheet,
            value=policy_key,
            label="id field",
        )
        if policy.get("label") is not None:
            _merge_scalar_target_default(
                label_by_target,
                target_key=target_key,
                target_sheet=target_sheet,
                value=str(policy["label"]),
                label="label field",
            )

        global_helpers = (
            _list_value(defaults.get("helper_fields"))
            if "helper_fields" in defaults
            else None
        )
        if global_helpers is not None and global_helpers != default_helpers:
            raise ValueError(
                f"Inline helper_fields {global_helpers!r} conflict with resolved "
                f"FK helper policy for target {target_key!r}: {default_helpers!r}"
            )

        _merge_helper_target_default(
            by_target,
            target_key=target_key,
            target_sheet=target_sheet,
            helpers=default_helpers,
        )

        fk_column = str(policy.get("fk_column") or f"{policy_key}_({target_key})")
        if fk_column in by_fk:
            inline = _list_value(by_fk[fk_column])
            if inline != default_helpers:
                raise ValueError(
                    f"Inline helper_fields_by_fk for {fk_column!r} conflict with resolved "
                    f"FK helper policy for target {target_key!r}: {default_helpers!r}"
                )

    execution_defaults["id_field_by_target"] = id_by_target
    execution_defaults["helper_fields_by_target"] = by_target
    if resolved_helper_prefix is not None:
        execution_defaults["helper_prefix"] = resolved_helper_prefix
    if label_by_target:
        execution_defaults["label_field_by_target"] = label_by_target
    return execution_defaults, policies


def _fk_policies(frames: Frames) -> dict[str, dict[str, Any]]:
    meta = frames.get("_meta")
    if not isinstance(meta, dict):
        return {}
    helper_policies = meta.get("helper_policies")
    if not isinstance(helper_policies, dict):
        return {}
    raw_policies = helper_policies.get("fk")
    if not isinstance(raw_policies, dict):
        return {}

    sheet_keys = {
        normalize_sheet_key(sheet_name): sheet_name
        for sheet_name, _df in iter_data_frames(frames)
    }
    policies: dict[str, dict[str, Any]] = {}
    for raw_target, raw_policy in raw_policies.items():
        if not isinstance(raw_policy, dict):
            continue
        target_key = str(raw_policy.get("target") or normalize_sheet_key(str(raw_target)))
        if target_key not in sheet_keys:
            raise KeyError(f"FK helper policy target {target_key!r} not found in frames")
        policy = dict(raw_policy)
        policy["target"] = target_key
        policy.setdefault("target_sheet", sheet_keys[target_key])
        policies[target_key] = policy
    return policies


def _merge_scalar_target_default(
    mapping: dict[str, Any],
    *,
    target_key: str,
    target_sheet: str,
    value: str,
    label: str,
) -> None:
    for key in (target_key, target_sheet):
        if key in mapping and str(mapping[key]) != value:
            raise ValueError(
                f"Inline {label} for FK target {target_key!r} conflicts with "
                f"resolved FK helper policy: {value!r}"
            )
    mapping[target_key] = value


def _merge_helper_target_default(
    mapping: dict[str, Any],
    *,
    target_key: str,
    target_sheet: str,
    helpers: list[str],
) -> None:
    for key in (target_key, target_sheet):
        if key in mapping:
            inline = _list_value(mapping[key])
            if inline != helpers:
                raise ValueError(
                    f"Inline helper_fields_by_target for FK target {target_key!r} "
                    f"conflict with resolved FK helper policy: {helpers!r}"
                )
    mapping[target_key] = helpers


def _validate_fk_policy_usage(
    fk_defs_by_sheet: dict[str, Any],
    fk_policies: dict[str, dict[str, Any]],
) -> None:
    if not fk_policies:
        return
    for fk_defs in fk_defs_by_sheet.values():
        for fk in fk_defs:
            policy = fk_policies.get(fk.target_sheet_key)
            if policy is None:
                continue
            if "allowed_helpers" not in policy:
                continue
            allowed = _list_value(policy.get("allowed_helpers"))
            if fk.value_field not in allowed:
                raise ValueError(
                    f"FK helper field {fk.value_field!r} for target {fk.target_sheet_key!r} "
                    f"is not in allowed list {allowed!r}"
                )


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    else:
        values = [str(item) for item in value]
    return list(dict.fromkeys(item for item in values if item))


def _write_helper_provenance(
    out: dict[str, Any],
    fk_defs_by_sheet: dict[str, Any],
) -> None:
    """Persist derived helper provenance into ``_meta["derived"]["sheets"]``."""
    has_any_fks = any(bool(fds) for fds in fk_defs_by_sheet.values())
    existing_meta = out.get("_meta")
    has_existing_prov = bool(
        ((existing_meta or {}).get("derived") or {}).get("sheets")
    )
    if not (has_any_fks or has_existing_prov or existing_meta is not None):
        return

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


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def drop_helpers(frames: Frames, *, prefix: str = "_") -> Frames:
    """Remove helper columns and clean up derived provenance.

    When derived helper provenance exists in ``_meta["derived"]["sheets"]``,
    columns listed there are removed first and the provenance entries are
    cleaned up.  Prefix-based removal remains as backward-compatible fallback
    for frames without provenance metadata.
    """
    out: dict[str, Any] = {}
    copy_reserved_frames(frames, out)
    meta: dict[str, Any] = dict(out.get("_meta") or {})
    derived_sheets: dict[str, Any] = (meta.get("derived") or {}).get("sheets") or {}

    for sheet, df in iter_data_frames(frames):
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
            cols = [c for c in df.columns if not _visible_label(c).startswith(prefix)]
            out[sheet] = df.loc[:, cols]

    _clean_helper_provenance(out, meta, derived_sheets)
    return out


def _visible_label(col: Any) -> str:
    """Extract the human-visible label from a (possibly tuple) column header."""
    if isinstance(col, tuple):
        for part in col:
            label = str(part)
            if label:
                return label
        return ""
    return str(col)


def _clean_helper_provenance(
    out: dict[str, Any],
    meta: dict[str, Any],
    derived_sheets: dict[str, Any],
) -> None:
    """Remove helper_columns provenance entries after helpers have been dropped."""
    if not derived_sheets:
        return

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
