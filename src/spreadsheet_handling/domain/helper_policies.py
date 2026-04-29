"""Configuration-producing helpers for resolved helper policies."""
from __future__ import annotations

from typing import Any

import pandas as pd
from pandas.api import types as pd_types

from ..core.fk import normalize_sheet_key
from ..frame_keys import iter_data_frames

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
    _validate_columns(keys, lookup_df, lookup, "key", frame_kind="lookup")

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

    _validate_columns(allowed, lookup_df, lookup, "allowed helper", frame_kind="lookup")
    _validate_columns(defaults, lookup_df, lookup, "default helper", frame_kind="lookup")

    disallowed_defaults = [field for field in defaults if field not in allowed]
    if disallowed_defaults:
        raise ValueError(
            f"default_helpers {disallowed_defaults} must be included in allowed_helpers "
            f"for lookup {lookup!r}"
        )

    resolved_order = dict(order or {})
    sort_by = _as_list(resolved_order.get("sort_by"))
    if sort_by:
        _validate_columns(sort_by, lookup_df, lookup, "sort_by", frame_kind="lookup")
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


def configure_fk_helpers(
    frames: Frames,
    *,
    target: str | None = None,
    targets: dict[str, Any] | str | None = None,
    key: str | None = None,
    label: str | None = None,
    allowed_helpers: list[str] | str | None = None,
    default_helpers: list[str] | str | None = None,
    helper_prefix: str = "_",
    fk_column: str | None = None,
    fk_columns: dict[str, Any] | None = None,
    auto: dict[str, Any] | None = None,
) -> Frames:
    """Write resolved FK-helper policies to ``_meta.helper_policies.fk``.

    ``target`` configures one FK target. ``targets`` accepts either a mapping
    of target names to per-target configuration or ``"auto"`` for constrained
    inference from current data frames.
    """
    if target is not None and targets is not None:
        raise ValueError("Use either target or targets for configure_fk_helpers, not both")

    policy_specs = _fk_policy_specs(
        frames,
        target=target,
        targets=targets,
        key=key,
        label=label,
        allowed_helpers=allowed_helpers,
        default_helpers=default_helpers,
        helper_prefix=helper_prefix,
        fk_column=fk_column,
        fk_columns=fk_columns,
        auto=auto or {},
    )
    if not policy_specs:
        raise ValueError("configure_fk_helpers needs at least one target policy")

    out = dict(frames)
    meta = dict(out.get("_meta") or {})
    helper_policies = dict(meta.get("helper_policies") or {})
    fk_policies = dict(helper_policies.get("fk") or {})
    for policy in policy_specs:
        fk_policies[policy["target"]] = policy
    helper_policies["fk"] = fk_policies
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
    *,
    frame_kind: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise KeyError(f"{label} column(s) {missing} not found in {frame_kind} frame {frame_name!r}")


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


def _fk_policy_specs(
    frames: Frames,
    *,
    target: str | None,
    targets: dict[str, Any] | str | None,
    key: str | None,
    label: str | None,
    allowed_helpers: list[str] | str | None,
    default_helpers: list[str] | str | None,
    helper_prefix: str,
    fk_column: str | None,
    fk_columns: dict[str, Any] | None,
    auto: dict[str, Any],
) -> list[dict[str, Any]]:
    if targets == "auto":
        return _auto_fk_policy_specs(frames, auto=auto, helper_prefix=helper_prefix)

    if isinstance(targets, dict):
        policies: list[dict[str, Any]] = []
        for target_name, raw_cfg in targets.items():
            cfg = dict(raw_cfg or {})
            nested_fk_columns = cfg.get("fk_columns")
            policies.append(
                _build_fk_policy(
                    frames,
                    target=str(target_name),
                    key=cfg.get("key"),
                    label=cfg.get("label"),
                    allowed_helpers=cfg.get("allowed_helpers"),
                    default_helpers=cfg.get("default_helpers"),
                    helper_prefix=str(cfg.get("helper_prefix", helper_prefix)),
                    fk_column=cfg.get("fk_column"),
                    fk_columns=nested_fk_columns if isinstance(nested_fk_columns, dict) else None,
                    auto={**auto, **dict(cfg.get("auto") or {})},
                )
            )
        return policies

    if targets is not None:
        raise TypeError("targets must be a mapping or 'auto'")
    if target is None:
        raise ValueError("configure_fk_helpers needs target or targets")

    return [
        _build_fk_policy(
            frames,
            target=target,
            key=key,
            label=label,
            allowed_helpers=allowed_helpers,
            default_helpers=default_helpers,
            helper_prefix=helper_prefix,
            fk_column=fk_column,
            fk_columns=fk_columns,
            auto=auto,
        )
    ]


def _build_fk_policy(
    frames: Frames,
    *,
    target: str,
    key: str | None,
    label: str | None,
    allowed_helpers: list[str] | str | None,
    default_helpers: list[str] | str | None,
    helper_prefix: str,
    fk_column: str | None,
    fk_columns: dict[str, Any] | None,
    auto: dict[str, Any],
) -> dict[str, Any]:
    target_name, target_key = _resolve_target_frame(frames, target)
    target_df = _require_frame(frames, target_name)
    resolved_key = _resolve_fk_key(target_df, key=key, auto=auto, target=target_name)
    _validate_columns([resolved_key], target_df, target_name, "key", frame_kind="target")

    if label is not None:
        _validate_columns([label], target_df, target_name, "label", frame_kind="target")

    allowed = _resolve_allowed_helpers(
        allowed_helpers,
        lookup_df=target_df,
        keys=[resolved_key],
        auto=_auto_helper_config(auto),
    )
    defaults = _resolve_default_helpers(
        default_helpers,
        allowed_helpers=allowed,
        auto=_auto_helper_config(auto),
    )

    _validate_columns(allowed, target_df, target_name, "allowed helper", frame_kind="target")
    _validate_columns(defaults, target_df, target_name, "default helper", frame_kind="target")

    disallowed_defaults = [field for field in defaults if field not in allowed]
    if disallowed_defaults:
        raise ValueError(
            f"default_helpers {disallowed_defaults} must be included in allowed_helpers "
            f"for FK target {target_name!r}"
        )

    resolved_fk_column = _resolve_fk_column(
        fk_column=fk_column,
        fk_columns=fk_columns,
        key=resolved_key,
        target_key=target_key,
        target_name=target_name,
        auto=auto,
    )

    policy = {
        "target": target_key,
        "target_sheet": target_name,
        "key": resolved_key,
        "allowed_helpers": allowed,
        "default_helpers": defaults,
        "helper_prefix": helper_prefix,
        "fk_column": resolved_fk_column,
    }
    if label is not None:
        policy["label"] = label
    return policy


def _auto_fk_policy_specs(
    frames: Frames,
    *,
    auto: dict[str, Any],
    helper_prefix: str,
) -> list[dict[str, Any]]:
    candidates = _as_list(auto.get("id_column_candidates") or ["id"])
    policies: list[dict[str, Any]] = []
    for sheet_name, df in iter_data_frames(frames):
        key = next((candidate for candidate in candidates if candidate in df.columns), None)
        if key is None:
            continue
        policies.append(
            _build_fk_policy(
                frames,
                target=sheet_name,
                key=key,
                label=None,
                allowed_helpers="auto",
                default_helpers="auto",
                helper_prefix=helper_prefix,
                fk_column=None,
                fk_columns=None,
                auto=auto,
            )
        )
    return policies


def _resolve_target_frame(frames: Frames, target: str) -> tuple[str, str]:
    if target in frames and isinstance(frames[target], pd.DataFrame):
        return target, normalize_sheet_key(target)

    matches = [
        (sheet_name, sheet_key)
        for sheet_name, _df in iter_data_frames(frames)
        for sheet_key in [normalize_sheet_key(sheet_name)]
        if sheet_key == target
    ]
    if not matches:
        raise KeyError(f"Expected target DataFrame {target!r} in frames")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous FK target {target!r}; matched {[name for name, _ in matches]}")
    return matches[0]


def _resolve_fk_key(
    target_df: pd.DataFrame,
    *,
    key: str | None,
    auto: dict[str, Any],
    target: str,
) -> str:
    if key is not None:
        return str(key)
    candidates = _as_list(auto.get("id_column_candidates") or ["id"])
    for candidate in candidates:
        if candidate in target_df.columns:
            return candidate
    raise ValueError(
        f"No FK key configured for target {target!r}; tried candidates {candidates}"
    )


def _resolve_fk_column(
    *,
    fk_column: str | None,
    fk_columns: dict[str, Any] | None,
    key: str,
    target_key: str,
    target_name: str,
    auto: dict[str, Any],
) -> str:
    if fk_column is not None:
        return str(fk_column)
    convention = (fk_columns or {}).get("convention")
    if convention is None:
        convention = auto.get("fk_column_pattern")
    if convention is not None:
        return str(convention).format(key=key, target=target_key, sheet=target_name)
    return f"{key}_({target_key})"


def _auto_helper_config(auto: dict[str, Any]) -> dict[str, Any]:
    helper_candidates = auto.get("helper_candidates")
    # FK-facing config names this block "allowed_helpers"; the shared lookup
    # resolver expects the same candidate policy under "helper_candidates".
    if helper_candidates is None and isinstance(auto.get("allowed_helpers"), dict):
        helper_candidates = auto["allowed_helpers"]
    default_helpers = auto.get("default_helpers")
    resolved: dict[str, Any] = dict(auto)
    if helper_candidates is not None:
        resolved["helper_candidates"] = helper_candidates
    if default_helpers is not None:
        resolved["default_helpers"] = default_helpers
    return resolved
