"""Explicit helper lookup enrichment.

Joins a source frame with a lookup frame by explicit keys and projects
configured helper fields.  Implements FTR-EXPLICIT-HELPER-LOOKUP-POLICY-P4.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

Frames = dict[str, Any]

_VALID_HELPER_POSITIONS = {"after_data", "before_key"}
_VALID_MISSING_MODES = {"fail", "empty"}


def enrich_lookup(
    frames: Frames,
    *,
    source: str,
    lookup: str,
    output: str,
    key: str | None = None,
    keys: list[str] | None = None,
    on: str | list[str] | None = None,
    helpers: dict[str, Any] | str | None = None,
    order: dict[str, Any] | None = None,
    missing: str | None = None,
) -> Frames:
    """Enrich *source* with helper columns from *lookup* by joining on configured keys.

    Parameters
    ----------
    source:
        Name of the source relation in *frames*.
    lookup:
        Name of the lookup relation in *frames*.
    output:
        Name for the enriched output relation written into *frames*.
    key:
        Preferred YAML-safe spelling for one join key.
    keys:
        Preferred YAML-safe spelling for multiple join keys.
    on:
        Legacy join key spelling. In YAML, quote it as ``"on"`` or prefer
        ``key``/``keys`` because unquoted ``on:`` is boolean-like in YAML 1.1.
    helpers:
        Controls which helper fields are projected from the lookup table.

        - ``dict`` with ``fields`` (list of column names to project),
          optional ``allowed`` (allowlist), optional ``default`` (defaults).
        - ``"default"`` – use ``default`` from a matching helper policy in
          ``_meta["helper_policies"]["lookup"][<lookup>]``.
        - ``None`` – no helper projection (only the join key is used).
    order:
        Optional dict with ``helper_position`` (``"before_key"`` or
        ``"after_data"``, default ``"after_data"``) and/or ``sort_by``
        (list of columns to sort the result by).
    missing:
        How to handle source rows without a matching lookup key.
        ``"fail"`` raises on unmatched rows.
        ``"empty"`` fills missing helper values with ``""``.
        When omitted and a resolved helper policy exists, the policy value is used.
    """
    policy = _resolve_policy(lookup, frames)
    join_keys = _resolve_join_keys(
        on=on,
        key=key,
        keys=keys,
        policy=policy,
        lookup=lookup,
    )
    missing_mode = _resolve_missing(missing, policy, lookup)
    order_cfg = _resolve_order(order, policy, lookup)

    if missing_mode not in _VALID_MISSING_MODES:
        raise ValueError(
            f"Invalid missing mode {missing_mode!r}; expected one of {sorted(_VALID_MISSING_MODES)}"
        )

    source_df = _require_frame(frames, source)
    lookup_df = _require_frame(frames, lookup)

    for key in join_keys:
        if key not in source_df.columns:
            raise KeyError(f"Join key {key!r} not found in source frame {source!r}")
        if key not in lookup_df.columns:
            raise KeyError(f"Join key {key!r} not found in lookup frame {lookup!r}")

    _check_duplicate_lookup_keys(lookup_df, join_keys, lookup)

    fields = _resolve_fields(helpers, lookup, frames)
    sort_by = order_cfg.get("sort_by")
    projection_fields = _fields_with_sort_helpers(fields, join_keys, sort_by, lookup_df)
    if projection_fields is not None:
        _validate_fields(projection_fields, lookup_df, lookup)
        allowed = _resolve_allowed(helpers, lookup, frames)
        if allowed is not None:
            _check_allowed(projection_fields, allowed, lookup)
        _check_column_conflict(source_df, join_keys, projection_fields, source)

    helper_cols = _build_helper_projection(lookup_df, join_keys, projection_fields)

    enriched = source_df.merge(helper_cols, on=join_keys, how="left")

    if missing_mode == "fail":
        _check_unmatched_rows(enriched, source_df, join_keys, fields, source, lookup)

    helper_position = order_cfg.get("helper_position", "after_data")
    if helper_position not in _VALID_HELPER_POSITIONS:
        raise ValueError(
            f"Invalid helper_position {helper_position!r}; "
            f"expected one of {sorted(_VALID_HELPER_POSITIONS)}"
        )

    if sort_by:
        _check_sort_columns(sort_by, enriched, output)
        enriched = enriched.sort_values(sort_by, na_position="last").reset_index(drop=True)
        enriched = _drop_temporary_sort_helpers(enriched, source_df, fields, sort_by)

    if helper_position == "before_key" and fields is not None:
        enriched = _reorder_helpers_before_key(enriched, join_keys, fields)

    enriched = enriched.where(pd.notnull(enriched), "")

    out = dict(frames)
    out[output] = enriched
    _write_provenance(out, output, lookup, join_keys, fields)
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_frame(frames: Frames, name: str) -> pd.DataFrame:
    value = frames.get(name)
    if not isinstance(value, pd.DataFrame):
        raise KeyError(f"Expected DataFrame {name!r} in frames")
    return value


def _check_duplicate_lookup_keys(
    lookup_df: pd.DataFrame, join_keys: list[str], lookup: str,
) -> None:
    if lookup_df.duplicated(subset=join_keys, keep=False).any():
        raise ValueError(
            f"Lookup frame {lookup!r} contains duplicate keys on {join_keys}"
        )


def _check_column_conflict(
    source_df: pd.DataFrame,
    join_keys: list[str],
    fields: list[str],
    source: str,
) -> None:
    key_set = set(join_keys)
    conflict = [f for f in fields if f not in key_set and f in source_df.columns]
    if conflict:
        raise ValueError(
            f"Helper field(s) {conflict} already exist in source frame {source!r}; "
            f"this would silently shadow the lookup values"
        )


def _check_unmatched_rows(
    enriched: pd.DataFrame,
    source_df: pd.DataFrame,
    join_keys: list[str],
    fields: list[str] | None,
    source: str,
    lookup: str,
) -> None:
    check_cols = fields if fields else join_keys
    helper_cols = [c for c in check_cols if c not in join_keys]
    if not helper_cols:
        return
    has_null = enriched[helper_cols].isnull().any(axis=1)
    if has_null.any():
        bad_keys = enriched.loc[has_null, join_keys].to_dict(orient="records")
        raise ValueError(
            f"Source {source!r} has rows with no match in lookup {lookup!r}: "
            f"{bad_keys[:5]}"
        )


def _check_sort_columns(
    sort_by: list[str], enriched: pd.DataFrame, output: str,
) -> None:
    missing = [c for c in sort_by if c not in enriched.columns]
    if missing:
        raise ValueError(
            f"sort_by column(s) {missing} not found in enriched frame {output!r}"
        )


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


def _fields_with_sort_helpers(
    fields: list[str] | None,
    join_keys: list[str],
    sort_by: list[str] | None,
    lookup_df: pd.DataFrame,
) -> list[str] | None:
    if fields is None:
        return None
    extra_sort_fields = [
        field for field in (sort_by or [])
        if field not in join_keys and field in lookup_df.columns
    ]
    return list(dict.fromkeys(fields + extra_sort_fields))


def _drop_temporary_sort_helpers(
    enriched: pd.DataFrame,
    source_df: pd.DataFrame,
    fields: list[str] | None,
    sort_by: list[str] | None,
) -> pd.DataFrame:
    if fields is None:
        return enriched
    output_fields = set(fields)
    source_fields = set(source_df.columns)
    temporary = [
        field for field in (sort_by or [])
        if field not in output_fields and field not in source_fields and field in enriched.columns
    ]
    if not temporary:
        return enriched
    return enriched.drop(columns=temporary)


def _validate_fields(fields: list[str], lookup_df: pd.DataFrame, lookup: str) -> None:
    missing = [f for f in fields if f not in lookup_df.columns]
    if missing:
        raise KeyError(
            f"Helper field(s) {missing} not found in lookup frame {lookup!r}"
        )


def _check_allowed(fields: list[str], allowed: list[str], lookup: str) -> None:
    disallowed = [f for f in fields if f not in allowed]
    if disallowed:
        raise ValueError(
            f"Helper field(s) {disallowed} not in allowed list for lookup {lookup!r}"
        )


def _build_helper_projection(
    lookup_df: pd.DataFrame,
    join_keys: list[str],
    fields: list[str] | None,
) -> pd.DataFrame:
    if fields is None:
        return lookup_df.loc[:, join_keys].copy()
    cols = list(dict.fromkeys(join_keys + fields))
    return lookup_df.loc[:, cols].copy()


def _reorder_helpers_before_key(
    df: pd.DataFrame,
    join_keys: list[str],
    fields: list[str],
) -> pd.DataFrame:
    current = list(df.columns)
    helper_set = set(fields) - set(join_keys)
    non_helper = [c for c in current if c not in helper_set]
    key_idx = min(
        (non_helper.index(k) for k in join_keys if k in non_helper),
        default=0,
    )
    ordered = non_helper[:key_idx] + [f for f in fields if f in helper_set] + non_helper[key_idx:]
    return df[ordered]


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def _write_provenance(
    out: Frames,
    output: str,
    lookup: str,
    join_keys: list[str],
    fields: list[str] | None,
) -> None:
    if fields is None:
        return
    meta: dict[str, Any] = dict(out.get("_meta") or {})
    derived: dict[str, Any] = meta.setdefault("derived", {})
    derived_sheets: dict[str, Any] = derived.setdefault("sheets", {})
    derived_sheets.setdefault(output, {})["enrich_lookup"] = {
        "lookup": lookup,
        "on": join_keys,
        "helper_columns": list(fields),
    }
    out["_meta"] = meta
