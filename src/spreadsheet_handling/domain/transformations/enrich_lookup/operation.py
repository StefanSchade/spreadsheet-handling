"""Explicit helper lookup enrichment.

Joins a source frame with a lookup frame by explicit keys and projects
configured helper fields.  Implements FTR-EXPLICIT-HELPER-LOOKUP-POLICY-P4.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from spreadsheet_handling.core.formulas import lookup_formula

from .policy import (
    _FORMULA_MODES,
    _ResolvedKeys,
    _resolve_allowed,
    _resolve_fields,
    _resolve_join_keys,
    _resolve_missing,
    _resolve_order,
    _resolve_policy,
    _resolve_value_mode,
)

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
    source_key: str | None = None,
    lookup_key: str | None = None,
    helpers: dict[str, Any] | str | None = None,
    order: dict[str, Any] | None = None,
    missing: str | None = None,
    helper_value_mode: str | None = None,
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
    source_key:
        Source-side join key for the opt-in *asymmetric* mode. Must be supplied
        together with ``lookup_key`` and is mutually exclusive with
        ``key``/``keys``/``on``. Use this when the join key has a different name
        in the source frame than in the lookup frame (e.g. source ``story_id``
        matched against lookup ``id``). The source key is the one that appears
        in the output frame; the lookup key never leaks into the output.

        An explicit ``source_key``/``lookup_key`` pair is *authoritative for
        join-key selection*: it ignores a configured helper-policy ``key`` while
        still consuming the policy's non-key settings (helper ``fields``,
        ``allowed`` fields, ``order``, ``missing`` behaviour, and
        ``helper_value_mode``). A symmetric inline key, by contrast, is
        reconciled against the policy ``key`` and fails on conflict. A requested
        helper or temporary lookup sort field that equals either the source key
        or the lookup key is rejected with a ``ValueError`` before projection,
        because it would leak the lookup key or overwrite the source key. This
        safety follows the selected asymmetric mode even when the two key names
        are *equal*: the single key is the authoritative source key and cannot
        also be requested as a helper (sorting the output by that key stays
        valid). A duplicate requested helper name is likewise rejected before
        projection.
    lookup_key:
        Lookup-side join key for the asymmetric mode; the companion of
        ``source_key``.
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
    helper_value_mode:
        ``"values"`` (default) merges copied helper values via join.
        ``"formula"`` stores backend-neutral ``LookupFormulaSpec`` objects as
        cell values so the rendered workbook shows live XLOOKUP formulas
        referencing the lookup sheet.
    """
    policy = _resolve_policy(lookup, frames)
    resolved = _resolve_join_keys(
        on=on,
        key=key,
        keys=keys,
        source_key=source_key,
        lookup_key=lookup_key,
        policy=policy,
        lookup=lookup,
    )
    source_keys = list(resolved.source_keys)
    lookup_keys = list(resolved.lookup_keys)
    missing_mode = _resolve_missing(missing, policy, lookup)
    order_cfg = _resolve_order(order, policy, lookup)
    value_mode = _resolve_value_mode(helper_value_mode, policy)

    if missing_mode not in _VALID_MISSING_MODES:
        raise ValueError(
            f"Invalid missing mode {missing_mode!r}; expected one of {sorted(_VALID_MISSING_MODES)}"
        )

    source_df = _require_frame(frames, source)
    lookup_df = _require_frame(frames, lookup)

    for source_key_name in source_keys:
        if source_key_name not in source_df.columns:
            raise KeyError(
                f"Join key {source_key_name!r} not found in source frame {source!r}"
            )
    for lookup_key_name in lookup_keys:
        if lookup_key_name not in lookup_df.columns:
            raise KeyError(
                f"Join key {lookup_key_name!r} not found in lookup frame {lookup!r}"
            )

    _check_duplicate_lookup_keys(lookup_df, lookup_keys, lookup)

    fields = _resolve_fields(helpers, lookup, frames)
    _check_duplicate_helper_fields(fields, lookup)
    sort_by = order_cfg.get("sort_by")
    projection_fields = _fields_with_sort_helpers(fields, source_keys, sort_by, lookup_df)
    if projection_fields is not None:
        _validate_fields(projection_fields, lookup_df, lookup)
        allowed = _resolve_allowed(helpers, lookup, frames)
        if allowed is not None:
            _check_allowed(projection_fields, allowed, lookup)
        _check_column_conflict(source_df, source_keys, projection_fields, source)
        _check_key_helper_collision(resolved, projection_fields, source, lookup)

    use_formulas = value_mode in _FORMULA_MODES

    if use_formulas and missing_mode == "fail":
        raise ValueError(
            "missing='fail' cannot be enforced with helper_value_mode='formula'; "
            "use missing='empty' or value mode"
        )

    if use_formulas and sort_by:
        lookup_sort_cols = [c for c in sort_by if c not in source_df.columns]
        if lookup_sort_cols:
            raise ValueError(
                f"sort_by columns {lookup_sort_cols} from the lookup frame "
                "cannot be used with helper_value_mode='formula'; "
                "sort_by is only supported for source-frame columns in formula mode"
            )

    if use_formulas and fields is not None:
        enriched = _build_formula_enrichment(
            source_df, lookup, source_keys, lookup_keys, fields, missing_mode,
        )
    else:
        helper_cols = _build_helper_projection(
            lookup_df, source_keys, lookup_keys, projection_fields,
        )
        enriched = source_df.merge(helper_cols, on=source_keys, how="left")

        if missing_mode == "fail":
            _check_unmatched_rows(enriched, source_df, source_keys, fields, source, lookup)

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
        enriched = _reorder_helpers_before_key(enriched, source_keys, fields)

    if not use_formulas:
        enriched = enriched.where(pd.notnull(enriched), "")

    out = dict(frames)
    out[output] = enriched
    _write_provenance(out, output, lookup, resolved, fields)
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


def _check_duplicate_helper_fields(fields: list[str] | None, lookup: str) -> None:
    """Reject duplicate requested helper names before any projection/output.

    A duplicate entry in the resolved helper ``fields`` (whether spelled inline
    in ``helpers.fields`` or supplied by a helper policy's ``default_helpers``)
    would otherwise produce duplicate output labels under ``before_key`` and
    duplicate ``helper_columns`` provenance in both values and formula modes
    (review R002-IMP-003). The rule is deterministic and identical across value
    modes and helper positions: each helper column may be requested at most
    once. This is intentionally a generic guard — the same silent
    duplicate-label/duplicate-provenance defect existed in symmetric mode via
    the retained ``fields`` list, and rejecting literal duplicates is a safe,
    backward-compatible tightening (no valid pipeline requests the same helper
    twice). A helper that is *also* named in ``sort_by`` is not a duplicate
    helper and stays valid.
    """
    if fields is None:
        return
    seen: set[str] = set()
    duplicates: list[str] = []
    for field in fields:
        if field in seen and field not in duplicates:
            duplicates.append(field)
        seen.add(field)
    if duplicates:
        raise ValueError(
            f"Duplicate helper field(s) {duplicates} requested for lookup {lookup!r}; "
            f"each helper column may be requested at most once."
        )


def _check_key_helper_collision(
    resolved: _ResolvedKeys,
    projection_fields: list[str],
    source: str,
    lookup: str,
) -> None:
    """Reject helper/sort fields that collide with an asymmetric key role.

    In asymmetric mode ``_build_helper_projection`` renames the lookup key to
    the source key before the merge, and formula mode assigns cells by field
    name. A projected field (a requested helper or a temporary lookup sort
    helper) that equals either key role would therefore silently:

    * expose the lookup key as an output column (field == lookup key);
    * overwrite the authoritative source key (field == source key); or
    * collapse onto the renamed source label and produce a duplicate output
      label / false helper provenance.

    Rather than surfacing as a pandas duplicate-label or ``KeyError`` after the
    merge (or, in formula mode, silently corrupting the output), these requests
    fail here with a clear domain ``ValueError`` before any projection, merge,
    or formula assignment.

    Safety follows the *selected public mode*, not label inequality (review
    R002-IMP-001). In explicit asymmetric mode with *equal* key names, the
    single key is the authoritative source key and cannot simultaneously be an
    independent derived helper; a requested helper equal to it is rejected as
    one collision spanning both roles. A source/output-key sort
    (``sort_by=[<key>]``) is *not* a projected helper — it never enters
    ``projection_fields`` because it equals the join key — so it stays valid.
    Symmetric mode keeps its established behaviour.
    """
    if not resolved.is_asymmetric:
        return
    source_key = resolved.source_key
    lookup_key = resolved.lookup_key
    for field in projection_fields:
        if source_key == lookup_key:
            if field == source_key:
                raise ValueError(
                    f"Helper/sort field {field!r} collides with the asymmetric join key "
                    f"for source {source!r} / lookup {lookup!r}; in explicit asymmetric "
                    f"mode {field!r} is the authoritative source key and cannot also be "
                    f"requested as an independent derived helper. Use a different lookup "
                    f"value column, or sort by the key without requesting it as a helper."
                )
            continue
        if field == lookup_key:
            raise ValueError(
                f"Helper/sort field {field!r} collides with the asymmetric lookup key "
                f"for lookup {lookup!r}; the lookup key must not be projected as an "
                f"output column because it would leak into the output. Rename the "
                f"lookup value or drop the field."
            )
        if field == source_key:
            raise ValueError(
                f"Helper/sort field {field!r} collides with the asymmetric source key "
                f"for source {source!r}; a helper must not overwrite the authoritative "
                f"source key. Choose a different lookup value column."
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
    source_keys: list[str],
    lookup_keys: list[str],
    fields: list[str] | None,
) -> pd.DataFrame:
    """Project the join key(s) and helper fields from the lookup frame.

    The projection is keyed by the *lookup*-side key name(s) and renamed to the
    *source*-side name(s) so the caller can merge on the source key. In the
    symmetric case the rename is a no-op; in the asymmetric case this keeps the
    lookup-side key name out of the merged output.
    """
    projection_fields = [] if fields is None else fields
    cols = list(dict.fromkeys(lookup_keys + projection_fields))
    projection = lookup_df.loc[:, cols].copy()
    rename = {
        lookup_name: source_name
        for lookup_name, source_name in zip(lookup_keys, source_keys)
        if lookup_name != source_name
    }
    if rename:
        projection = projection.rename(columns=rename)
    return projection


def _build_formula_enrichment(
    source_df: pd.DataFrame,
    lookup: str,
    source_keys: list[str],
    lookup_keys: list[str],
    fields: list[str],
    missing_mode: str,
) -> pd.DataFrame:
    """Build an enriched frame with LookupFormulaSpec objects as cell values."""
    enriched = source_df.copy()
    source_key = source_keys[0]
    lookup_key = lookup_keys[0]
    for field in fields:
        formula = lookup_formula(
            source_key_column=source_key,
            lookup_sheet=lookup,
            lookup_key_column=lookup_key,
            lookup_value_column=field,
            missing="",
        )
        enriched[field] = [formula for _ in range(len(enriched))]
    return enriched


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
    resolved: _ResolvedKeys,
    fields: list[str] | None,
) -> None:
    if fields is None:
        return
    meta: dict[str, Any] = dict(out.get("_meta") or {})
    derived: dict[str, Any] = meta.setdefault("derived", {})
    derived_sheets: dict[str, Any] = derived.setdefault("sheets", {})
    record: dict[str, Any] = {"lookup": lookup}
    if resolved.is_asymmetric:
        # Asymmetric mode: record the distinct source/lookup keys additively
        # instead of a misleading synthetic common ``on`` key. This shape is
        # written from the *selected* public mode, so an explicit asymmetric
        # pair with equal key names still records the asymmetric shape (IMP-003).
        record["source_key"] = resolved.source_key
        record["lookup_key"] = resolved.lookup_key
    else:
        # Symmetric mode: preserve the original observable provenance shape.
        record["on"] = list(resolved.source_keys)
    record["helper_columns"] = list(fields)
    derived_sheets.setdefault(output, {})["enrich_lookup"] = record
    out["_meta"] = meta
