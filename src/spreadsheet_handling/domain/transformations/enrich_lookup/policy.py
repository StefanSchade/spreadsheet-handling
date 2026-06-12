"""Helper-policy resolution for ``enrich_lookup``.

Reconciles inline arguments against ``_meta.helper_policies.lookup.<lookup>``
and returns the resolved join keys, missing mode, order, fields, allowed
fields, and value mode used by the public step. Bodies are verbatim moves
out of the original flat module.

``_VALUE_MODES`` / ``_FORMULA_MODES`` live here too because
``_resolve_value_mode`` references them; ``operation`` re-imports
``_FORMULA_MODES`` from ``.policy`` so the values stay single-sourced.
"""
from __future__ import annotations

from typing import Any

Frames = dict[str, Any]

_VALUE_MODES = {"value", "values"}
_FORMULA_MODES = {"formula", "formulas"}


def _resolve_policy(lookup: str, frames: Frames) -> dict[str, Any] | None:
    meta = frames.get("_meta")
    if not isinstance(meta, dict):
        return None
    policies = meta.get("helper_policies")
    if not isinstance(policies, dict):
        return None
    lookup_policies = policies.get("lookup")
    if isinstance(lookup_policies, dict) and isinstance(lookup_policies.get(lookup), dict):
        return lookup_policies[lookup]
    return None


def _resolve_join_keys(
    *,
    on: str | list[str] | None,
    key: str | None,
    keys: list[str] | None,
    policy: dict[str, Any] | None,
    lookup: str,
) -> list[str]:
    policy_key = policy.get("key") if policy is not None else None
    configured = {
        name: value
        for name, value in {"on": on, "key": key, "keys": keys}.items()
        if value is not None
    }
    if len(configured) > 1:
        raise ValueError(
            "Configure add_lookup_helpers join keys with exactly one of "
            "`key`, `keys`, or quoted legacy `\"on\"`; got "
            f"{sorted(configured)}"
        )

    if not configured:
        if policy_key is None:
            raise ValueError(f"No join key configured for lookup {lookup!r}")
        return [policy_key] if isinstance(policy_key, str) else list(policy_key)

    if key is not None:
        if not isinstance(key, str):
            raise TypeError(
                "add_lookup_helpers `key` must be a single string; "
                "use `keys` for multiple keys"
            )
        join_keys = [key]
    elif keys is not None:
        if isinstance(keys, str):
            raise TypeError("add_lookup_helpers `keys` must be a list; use `key` for a single key")
        join_keys = list(keys)
    else:
        join_keys = [on] if isinstance(on, str) else list(on or [])

    if policy_key is not None:
        policy_keys = [policy_key] if isinstance(policy_key, str) else list(policy_key)
        if join_keys != policy_keys:
            raise ValueError(
                f"Inline join key {join_keys!r} conflicts with resolved helper policy "
                f"for lookup {lookup!r}: {policy_keys!r}"
            )
    return join_keys


def _resolve_missing(
    missing: str | None,
    policy: dict[str, Any] | None,
    lookup: str,
) -> str:
    policy_missing = policy.get("missing") if policy is not None else None
    if missing is None:
        return str(policy_missing or "fail")
    if policy_missing is not None and missing != policy_missing:
        raise ValueError(
            f"Inline missing mode {missing!r} conflicts with resolved helper policy "
            f"for lookup {lookup!r}: {policy_missing!r}"
        )
    return missing


def _resolve_order(
    order: dict[str, Any] | None,
    policy: dict[str, Any] | None,
    lookup: str,
) -> dict[str, Any]:
    policy_order = policy.get("order") if policy is not None else None
    if order is None:
        return dict(policy_order or {})
    if policy_order and order != policy_order:
        raise ValueError(
            f"Inline order {order!r} conflicts with resolved helper policy "
            f"for lookup {lookup!r}: {policy_order!r}"
        )
    return dict(order)


def _resolve_fields(
    helpers: dict[str, Any] | str | None,
    lookup: str,
    frames: Frames,
) -> list[str] | None:
    if helpers is None:
        return None
    if isinstance(helpers, str):
        if helpers == "default":
            policy = _resolve_policy(lookup, frames)
            if policy is None:
                raise ValueError(
                    f"helpers='default' but no helper_policy for lookup {lookup!r} in _meta"
                )
            default = policy.get("default_helpers")
            if not default:
                raise ValueError(
                    f"helper_policy for {lookup!r} has no default_helpers"
                )
            return list(default)
        raise ValueError(f"Unknown helpers shorthand: {helpers!r}")
    if isinstance(helpers, dict):
        fields = helpers.get("fields")
        if fields is not None:
            return list(fields)
        default = helpers.get("default")
        if default is not None:
            configured = [default] if isinstance(default, str) else list(default)
            policy = _resolve_policy(lookup, frames)
            if policy is not None and policy.get("default_helpers") is not None:
                resolved = list(policy.get("default_helpers") or [])
                if configured != resolved:
                    raise ValueError(
                        f"Inline default helpers {configured!r} conflict with resolved "
                        f"helper policy for lookup {lookup!r}: {resolved!r}"
                    )
            return configured
        policy = _resolve_policy(lookup, frames)
        if policy is not None:
            return list(policy.get("default_helpers") or [])
        return None
    raise TypeError(f"Unsupported helpers type: {type(helpers)}")


def _resolve_allowed(
    helpers: dict[str, Any] | str | None,
    lookup: str,
    frames: Frames,
) -> list[str] | None:
    policy = _resolve_policy(lookup, frames)
    if isinstance(helpers, dict):
        allowed = helpers.get("allowed")
        if allowed is not None:
            inline_allowed = list(allowed)
            if policy is not None and policy.get("allowed_helpers") is not None:
                policy_allowed = list(policy.get("allowed_helpers") or [])
                if inline_allowed != policy_allowed:
                    raise ValueError(
                        f"Inline allowed helpers {inline_allowed!r} conflict with resolved "
                        f"helper policy for lookup {lookup!r}: {policy_allowed!r}"
                    )
            return inline_allowed
    if policy is not None:
        allowed = policy.get("allowed_helpers")
        if allowed is not None:
            return list(allowed)
    return None


def _resolve_value_mode(
    inline: str | None,
    policy: dict[str, Any] | None,
) -> str:
    policy_mode = policy.get("helper_value_mode") if policy is not None else None
    mode = str(inline or policy_mode or "values").lower()
    valid = _VALUE_MODES | _FORMULA_MODES
    if mode not in valid:
        raise ValueError(
            f"helper_value_mode must be one of {sorted(valid)}; got {mode!r}"
        )
    return mode
