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
    on: str | list[str],
    helpers: dict[str, Any] | str | None = None,
    order: dict[str, Any] | None = None,
    missing: str = "fail",
) -> Frames:
    """Enrich *source* with helper columns from *lookup* by joining on *on*.

    Parameters
    ----------
    source:
        Name of the source relation in *frames*.
    lookup:
        Name of the lookup relation in *frames*.
    output:
        Name for the enriched output relation written into *frames*.
    on:
        Join key column(s).  A single string or a list of strings.
    helpers:
        Controls which helper fields are projected from the lookup table.

        - ``dict`` with ``fields`` (list of column names to project),
          optional ``allowed`` (allowlist), optional ``default`` (defaults).
        - ``"default"`` – use ``default`` from a matching helper policy in
          ``_meta["helper_policies"][<lookup>]``.
        - ``None`` – no helper projection (only the join key is used).
    order:
        Optional dict with ``helper_position`` (``"before_key"`` or
        ``"after_data"``, default ``"after_data"``) and/or ``sort_by``
        (list of columns to sort the result by).
    missing:
        How to handle source rows without a matching lookup key.
        ``"fail"`` (default) raises on unmatched rows.
        ``"empty"`` fills missing helper values with ``""``.
    """
    if missing not in _VALID_MISSING_MODES:
        raise ValueError(
            f"Invalid missing mode {missing!r}; expected one of {sorted(_VALID_MISSING_MODES)}"
        )

    source_df = _require_frame(frames, source)
    lookup_df = _require_frame(frames, lookup)

    join_keys = [on] if isinstance(on, str) else list(on)
    for key in join_keys:
        if key not in source_df.columns:
            raise KeyError(f"Join key {key!r} not found in source frame {source!r}")
        if key not in lookup_df.columns:
            raise KeyError(f"Join key {key!r} not found in lookup frame {lookup!r}")

    _check_duplicate_lookup_keys(lookup_df, join_keys, lookup)

    fields = _resolve_fields(helpers, lookup, frames)
    if fields is not None:
        _validate_fields(fields, lookup_df, lookup)
        allowed = _resolve_allowed(helpers, lookup, frames)
        if allowed is not None:
            _check_allowed(fields, allowed, lookup)
        _check_column_conflict(source_df, join_keys, fields, source)

    helper_cols = _build_helper_projection(lookup_df, join_keys, fields)

    enriched = source_df.merge(helper_cols, on=join_keys, how="left")

    if missing == "fail":
        _check_unmatched_rows(enriched, source_df, join_keys, fields, source, lookup)

    order_cfg = order or {}

    helper_position = order_cfg.get("helper_position", "after_data")
    if helper_position not in _VALID_HELPER_POSITIONS:
        raise ValueError(
            f"Invalid helper_position {helper_position!r}; "
            f"expected one of {sorted(_VALID_HELPER_POSITIONS)}"
        )

    sort_by = order_cfg.get("sort_by")
    if sort_by:
        _check_sort_columns(sort_by, enriched, output)
        enriched = enriched.sort_values(sort_by, na_position="last").reset_index(drop=True)

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
    return policies.get(lookup)


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
            return list(default)
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
    if isinstance(helpers, dict):
        allowed = helpers.get("allowed")
        if allowed is not None:
            return list(allowed)
    policy = _resolve_policy(lookup, frames)
    if policy is not None:
        allowed = policy.get("allowed_helpers")
        if allowed is not None:
            return list(allowed)
    return None


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
