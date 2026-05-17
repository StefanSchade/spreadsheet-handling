"""Resolution and validation of FK helper policies from ``_meta`` and inline config.

Behavior-preserving split out of the former single ``fk_helpers`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-FK-HELPERS-P5).
"""
from __future__ import annotations

from typing import Any

from ....core.fk import normalize_sheet_key
from ....frame_keys import iter_data_frames

Frames = dict[str, Any]


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
