"""Configuration-producing helpers for resolved helper policies."""
from __future__ import annotations

from typing import Any

import pandas as pd
from pandas.api import types as pd_types

Frames = dict[str, Any]

_VALID_MISSING_MODES = {"fail", "empty"}


def configure_lookup_helpers(
    frames: Frames,
    *,
    lookup: str,
    key: str | list[str],
    allowed_helpers: list[str] | str | None = None,
    default_helpers: list[str] | str | None = None,
    missing: str = "fail",
    order: dict[str, Any] | None = None,
    auto: dict[str, Any] | None = None,
) -> Frames:
    """Write a resolved lookup-helper policy to ``_meta.helper_policies.lookup``."""
    if missing not in _VALID_MISSING_MODES:
        raise ValueError(
            f"Invalid missing mode {missing!r}; expected one of {sorted(_VALID_MISSING_MODES)}"
        )

    lookup_df = _require_frame(frames, lookup)
    keys = _as_list(key)
    _validate_columns(keys, lookup_df, lookup, "key")

    allowed = _resolve_allowed_helpers(
        allowed_helpers,
        lookup_df=lookup_df,
        keys=keys,
        auto=auto or {},
    )
    defaults = _resolve_default_helpers(
        default_helpers,
        allowed_helpers=allowed,
        auto=auto or {},
    )

    _validate_columns(allowed, lookup_df, lookup, "allowed helper")
    _validate_columns(defaults, lookup_df, lookup, "default helper")

    disallowed_defaults = [field for field in defaults if field not in allowed]
    if disallowed_defaults:
        raise ValueError(
            f"default_helpers {disallowed_defaults} must be included in allowed_helpers "
            f"for lookup {lookup!r}"
        )

    resolved_order = dict(order or {})
    sort_by = _as_list(resolved_order.get("sort_by"))
    if sort_by:
        _validate_columns(sort_by, lookup_df, lookup, "sort_by")
        disallowed_sort = [field for field in sort_by if field not in keys and field not in allowed]
        if disallowed_sort:
            raise ValueError(
                f"sort_by column(s) {disallowed_sort} must be included in allowed_helpers "
                f"for lookup {lookup!r}"
            )

    policy = {
        "key": key if isinstance(key, str) else keys,
        "allowed_helpers": allowed,
        "default_helpers": defaults,
        "missing": missing,
        "order": resolved_order,
    }

    out = dict(frames)
    meta = dict(out.get("_meta") or {})
    helper_policies = dict(meta.get("helper_policies") or {})
    lookup_policies = dict(helper_policies.get("lookup") or {})
    lookup_policies[lookup] = policy
    helper_policies["lookup"] = lookup_policies
    meta["helper_policies"] = helper_policies
    out["_meta"] = meta
    return out


def _require_frame(frames: Frames, name: str) -> pd.DataFrame:
    value = frames.get(name)
    if not isinstance(value, pd.DataFrame):
        raise KeyError(f"Expected DataFrame {name!r} in frames")
    return value


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _validate_columns(
    columns: list[str],
    frame: pd.DataFrame,
    frame_name: str,
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise KeyError(f"{label} column(s) {missing} not found in lookup frame {frame_name!r}")


def _resolve_allowed_helpers(
    value: list[str] | str | None,
    *,
    lookup_df: pd.DataFrame,
    keys: list[str],
    auto: dict[str, Any],
) -> list[str]:
    if value == "auto":
        return _auto_allowed_helpers(lookup_df, keys=keys, auto=auto)
    if value is None:
        return []
    return _dedupe(_as_list(value))


def _resolve_default_helpers(
    value: list[str] | str | None,
    *,
    allowed_helpers: list[str],
    auto: dict[str, Any],
) -> list[str]:
    if value == "auto":
        preferred = _as_list((auto.get("default_helpers") or {}).get("prefer"))
        defaults = [field for field in preferred if field in allowed_helpers]
        if defaults:
            return defaults
        return allowed_helpers[:1]
    if value is None:
        return []
    return _dedupe(_as_list(value))


def _auto_allowed_helpers(
    lookup_df: pd.DataFrame,
    *,
    keys: list[str],
    auto: dict[str, Any],
) -> list[str]:
    helper_candidates = auto.get("helper_candidates") or {}
    exclude = set(keys) | set(_as_list(helper_candidates.get("exclude")))
    include_kinds = set(_as_list(helper_candidates.get("include_if_dtype")))

    fields: list[str] = []
    for column in lookup_df.columns:
        column_name = str(column)
        if column_name in exclude:
            continue
        if include_kinds and not _dtype_matches(lookup_df[column], include_kinds):
            continue
        fields.append(column_name)
    return _dedupe(fields)


def _dtype_matches(series: pd.Series, include_kinds: set[str]) -> bool:
    normalized = {kind.lower() for kind in include_kinds}
    return (
        ("string" in normalized and (pd_types.is_string_dtype(series) or series.dtype == object))
        or ("integer" in normalized and pd_types.is_integer_dtype(series))
        or ("boolean" in normalized and pd_types.is_bool_dtype(series))
        or ("number" in normalized and pd_types.is_numeric_dtype(series))
    )


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
