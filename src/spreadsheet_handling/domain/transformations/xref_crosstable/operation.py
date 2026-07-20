"""Cross-table / XRef transformations.

This module owns the generic matrix <-> relation conversion used by the first
compact-transform slice.  It deliberately treats cell values as opaque.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain._cell_primitives import _is_empty_cell, _values_equal
from spreadsheet_handling.domain.pipeline_cleanup import mark_frames_for_cleanup

from .dense_axes import (
    _dense_axes_from_config_or_meta,
    _dense_axes_meta_payload,
    _ensure_relation_within_dense_axes,
    _plain_axis_value,
    _resolve_dense_axes,
)
from .primitives import (
    _META_KEY,
    _as_list,
    _ensure_column_identity_list,
    _ensure_column_identity_values,
    _ensure_columns,
    _ensure_flat_axis_labels,
    _ensure_unique_field_list,
    _ensure_unique_physical_labels,
    _ordered_values_equal,
    _require_frame,
    _xref_config,
)

Frames = dict[str, Any]


def expand_xref(
    frames: Mapping[str, Any],
    *,
    matrix: str,
    output: str,
    row_keys: str | Iterable[Any],
    value_columns: Iterable[Any] | None = None,
    column_key: str = "column_key",
    value: str = "value",
    drop_empty: bool = False,
    base_relation: str | None = None,
    drop_source: bool = False,
    name: str | None = None,
) -> Frames:
    """Expand a matrix/cross-table frame into explicit long-form rows.

    When base_relation is supplied, out-of-scope rows from that frame are
    appended after the recomposed in-scope rows (scoped recomposition).

    With ``drop_source=True`` the caller asserts that the expanded relation
    fully supersedes the matrix frame; the matrix is then marked for final
    domain cleanup via an explicit ``_meta.pipeline_cleanup`` drop command.
    The checkable value-loss condition is enforced: an explicit
    ``value_columns`` subset that would leave unexpanded matrix columns
    behind rejects ``drop_source``. Shape recovery for empty-only columns
    under ``drop_empty=True`` remains the caller's feature-local judgement
    (dense column intent or a retained matrix provides it).

    Column identities follow the carrier-stable contract: duplicate
    physical matrix labels are rejected before expansion, and the expanded
    labels must be unique, non-empty strings.
    """
    config_id = name or output
    if drop_source and matrix == output:
        raise ValueError("drop_source requires a distinct output frame")
    source = _require_frame(frames, matrix)
    # Every physical matrix label is a spreadsheet header of the roundtrip
    # artifact: enforce the carrier-stable contract (unique, non-empty
    # strings) on the whole physical header row before any pandas hashing
    # or selection, so unhashable/numeric/missing/duplicate labels get the
    # XRef diagnostic instead of raw pandas behavior.
    _ensure_column_identity_list(
        source.columns.tolist(), f"Frame {matrix!r} physical column labels"
    )
    row_key_cols = _as_list(row_keys, "row_keys")
    _ensure_flat_axis_labels(row_key_cols, "row_keys")
    _ensure_unique_field_list(row_key_cols, "row_keys")
    _ensure_columns(source, row_key_cols, frame_name=matrix, field_name="row_keys")
    # Load and physical-validate the base relation before any output-name set
    # construction or membership: a configured physical base field
    # (``column_key`` / ``value``) may be an unhashable label such as a list,
    # which must receive the deterministic XRef physical-label diagnostic
    # rather than a raw ``TypeError`` from the set built inside
    # ``_ensure_output_names_do_not_collide``.
    base_frame = None
    if base_relation is not None:
        base_frame = _require_frame(frames, base_relation)
        _ensure_unique_physical_labels(base_frame, frame_name=base_relation)
    _ensure_output_names_do_not_collide(row_key_cols, column_key=column_key, value=value)

    if value_columns is not None:
        value_cols = _as_list(value_columns, "value_columns")
        # Configured selectors are not yet validated (unlike the physical
        # header row above): route them through the identity validator before
        # any equality/membership so pd.NA, an ndarray, or a numeric/empty/
        # unhashable selector gets the deterministic XRef diagnostic instead
        # of a raw ambiguity error from the overlap check below. Only after
        # validation reduces them to valid string identities do overlap and
        # selection run.
        _ensure_column_identity_list(value_cols, f"Frame {matrix!r} value_columns")
    else:
        # Inferred value columns are a subset of the physical matrix header
        # row already validated above, so they are valid string identities.
        value_cols = [col for col in source.columns if col not in row_key_cols]
    row_key_overlap = [col for col in value_cols if col in row_key_cols]
    if row_key_overlap:
        raise ValueError(
            f"value_columns must not overlap row_keys: {row_key_overlap!r}; "
            "a row-identity field cannot also be a value column"
        )
    _ensure_columns(source, value_cols, frame_name=matrix, field_name="value_columns")
    if drop_source:
        unexpanded = [
            col
            for col in source.columns
            if col not in row_key_cols and col not in value_cols
        ]
        if unexpanded:
            raise ValueError(
                f"drop_source would lose matrix column(s) {unexpanded!r} that "
                "value_columns does not expand; expand every value column or "
                "keep the matrix frame"
            )

    records: list[dict[Any, Any]] = []
    in_scope_addresses: set[tuple[tuple[Any, ...], Any]] = set()
    for _, source_row in source.iterrows():
        row_identity = {row_key: source_row[row_key] for row_key in row_key_cols}
        row_id = tuple(source_row[row_key] for row_key in row_key_cols)
        for matrix_col in value_cols:
            in_scope_addresses.add((row_id, matrix_col))
            cell_value = source_row[matrix_col]
            if drop_empty and _is_empty_cell(cell_value):
                continue
            records.append({
                **row_identity,
                column_key: matrix_col,
                value: cell_value,
            })

    if base_frame is not None:
        # Already loaded and physical-validated above (before the output-name
        # collision check) so an unhashable configured base field is rejected
        # with the XRef diagnostic before any set/membership construction.
        _ensure_columns(
            base_frame,
            [*row_key_cols, column_key, value],
            frame_name=base_relation,
            field_name="row_keys/column_key/value",
        )
        # Out-of-scope rows join the output relation: their column
        # identities must satisfy the same carrier-stable contract as the
        # expanded matrix labels.
        _ensure_column_identity_values(
            base_frame[column_key].tolist(),
            f"Frame {base_relation!r} column_key {column_key!r} values",
        )
        for _, base_row in base_frame.iterrows():
            base_addr = (
                tuple(base_row[row_key] for row_key in row_key_cols),
                base_row[column_key],
            )
            if base_addr not in in_scope_addresses:
                records.append({
                    **{row_key: base_row[row_key] for row_key in row_key_cols},
                    column_key: base_row[column_key],
                    value: base_row[value],
                })

    relation = pd.DataFrame(records, columns=[*row_key_cols, column_key, value])
    out: dict[str, Any] = dict(frames)
    out[output] = relation
    previous_config = _xref_config(frames, config_id, matrix=matrix)
    dense_axes = (
        dict(previous_config["dense_axes"])
        if (
            isinstance(previous_config, Mapping)
            and isinstance(previous_config.get("dense_axes"), Mapping)
        )
        else None
    )
    # Minimal feature-local inverse intent: frame identity (legitimately
    # referencing frames that final cleanup may later remove), row-identity
    # vocabulary, and dense-axis intent riding along for a later contract.
    # ``column_keys`` is a run-local Resolution facet (same-run contract
    # reuse and sparse_defaults); the persistence boundary strips it.
    payload = {
        "matrix": matrix,
        "relation": output,
        "row_keys": list(row_key_cols),
        "column_keys": list(value_cols),
    }
    if dense_axes is not None:
        payload["dense_axes"] = dense_axes
    _write_xref_meta(
        out,
        config_id=config_id,
        payload=payload,
    )
    if drop_source:
        mark_frames_for_cleanup(out, [matrix])
    return out


def contract_xref(
    frames: Mapping[str, Any],
    *,
    relation: str,
    output: str,
    row_keys: str | Iterable[Any],
    column_key: str = "column_key",
    value: str = "value",
    column_keys: Iterable[Any] | None = None,
    fill_value: Any = "",
    dense_axes: Mapping[str, Any] | None = None,
    drop_source: bool = False,
    name: str | None = None,
) -> Frames:
    """Contract explicit long-form rows into a matrix/cross-table frame.

    With ``drop_source=True`` the caller asserts that the contracted matrix
    fully supersedes the relation frame; the relation is then marked for
    final domain cleanup via an explicit ``_meta.pipeline_cleanup`` drop
    command. The checkable value-loss conditions are enforced: the relation
    must contain no fields beyond ``row_keys + column_key + value`` (the
    matrix represents nothing else), and every relation column key must be
    covered by the matrix columns (a matrix that silently drops relation
    pairs cannot supersede the relation).

    Matrix column identities that participate in the roundtrip must be
    unique, non-empty strings (carrier-stable contract): relation
    ``column_key`` values and every column-identity source (explicit,
    metadata-derived, dense-derived) are validated before the matrix is
    built.
    """
    config_id = name or relation
    if drop_source and relation == output:
        raise ValueError("drop_source requires a distinct output frame")
    source = _require_frame(frames, relation)
    # Duplicate physical relation labels make row[field] indexing
    # non-scalar; reject before any selection, metadata, or cleanup write.
    _ensure_unique_physical_labels(source, frame_name=relation)
    row_key_cols = _as_list(row_keys, "row_keys")
    _ensure_flat_axis_labels(row_key_cols, "row_keys")
    _ensure_unique_field_list(row_key_cols, "row_keys")
    _ensure_columns(
        source,
        [*row_key_cols, column_key, value],
        frame_name=relation,
        field_name="row_keys/column_key/value",
    )
    _ensure_output_names_do_not_collide(row_key_cols, column_key=column_key, value=value)
    # Identity contract first: unhashable/missing values must get the
    # deterministic contract diagnostic, not a pandas hashtable error from
    # the duplicate-pair check below.
    _ensure_column_identity_values(
        source[column_key].tolist(),
        f"Frame {relation!r} column_key {column_key!r} values",
    )
    _ensure_unique_pairs(source, row_key_cols, column_key)
    if drop_source:
        represented = {*row_key_cols, column_key, value}
        unrepresented = [col for col in source.columns if col not in represented]
        if unrepresented:
            raise ValueError(
                f"drop_source would lose relation field(s) {unrepresented!r} "
                "that the matrix does not represent (only row_keys, "
                "column_key, and value are projected); project them "
                "separately or keep the relation frame"
            )

    dense_config = _dense_axes_from_config_or_meta(
        frames,
        dense_axes=dense_axes,
        config_id=config_id,
        relation=relation,
    )
    dense_resolved = _resolve_dense_axes(
        frames,
        dense_config=dense_config,
        row_keys=row_key_cols,
        column_key=column_key,
    )
    matrix_cols = _matrix_column_keys(
        frames,
        relation=relation,
        config_id=config_id,
        column_key=column_key,
        explicit_column_keys=column_keys,
        dense_resolved=dense_resolved,
    )
    # One identity contract for every column-identity source: explicit
    # column_keys, metadata-derived reuse, and dense-axis-derived lists all
    # arrive here as matrix_cols.
    _ensure_column_identity_list(matrix_cols, "column_keys")
    row_identities = (
        dense_resolved["row_identities"]
        if "row_identities" in dense_resolved
        else _ordered_row_identities(source, row_key_cols)
    )
    _ensure_relation_within_dense_axes(
        source,
        row_keys=row_key_cols,
        column_key=column_key,
        dense_resolved=dense_resolved,
    )
    if drop_source:
        _ensure_matrix_covers_relation_columns(
            source,
            column_key=column_key,
            matrix_cols=matrix_cols,
            normalize="column_keys" in dense_resolved,
        )

    values_by_pair = {
        (
            _relation_row_identity(
                source_row,
                row_key_cols,
                normalize="row_identities" in dense_resolved,
            ),
            _relation_column_identity(
                source_row[column_key],
                normalize="column_keys" in dense_resolved,
            ),
        ): source_row[value]
        for _, source_row in source.iterrows()
    }

    rows: list[dict[Any, Any]] = []
    for row_identity in row_identities:
        record = {
            row_key: row_identity[index]
            for index, row_key in enumerate(row_key_cols)
        }
        for matrix_col in matrix_cols:
            record[matrix_col] = values_by_pair.get((row_identity, matrix_col), fill_value)
        rows.append(record)

    matrix_frame = pd.DataFrame(rows, columns=[*row_key_cols, *matrix_cols])
    out: dict[str, Any] = dict(frames)
    out[output] = matrix_frame
    # Minimal feature-local inverse intent; see the expand_xref payload
    # comment for the retained fields and their concrete consumers.
    payload = {
        "relation": relation,
        "matrix": output,
        "row_keys": list(row_key_cols),
        "column_keys": list(matrix_cols),
    }
    dense_payload = _dense_axes_meta_payload(
        dense_config=dense_config,
        dense_resolved=dense_resolved,
        row_keys=row_key_cols,
        column_keys=matrix_cols,
    )
    if dense_payload is not None:
        payload["dense_axes"] = dense_payload
    _write_xref_meta(
        out,
        config_id=config_id,
        payload=payload,
    )
    if drop_source:
        mark_frames_for_cleanup(out, [relation])
    return out


def _ensure_output_names_do_not_collide(
    row_keys: list[Any],
    *,
    column_key: str,
    value: str,
) -> None:
    reserved = {column_key, value}
    collisions = [row_key for row_key in row_keys if row_key in reserved]
    if collisions:
        raise ValueError(f"row_keys collide with output column names: {collisions!r}")
    if column_key == value:
        raise ValueError("column_key and value output names must differ")


def _ensure_matrix_covers_relation_columns(
    relation: pd.DataFrame,
    *,
    column_key: str,
    matrix_cols: list[Any],
    normalize: bool,
) -> None:
    uncovered: list[Any] = []
    for raw_value in relation[column_key].tolist():
        value = _relation_column_identity(raw_value, normalize=normalize)
        if any(_values_equal(value, matrix_col) for matrix_col in matrix_cols):
            continue
        if not any(_values_equal(value, existing) for existing in uncovered):
            uncovered.append(value)
    if uncovered:
        raise ValueError(
            f"drop_source would lose relation column key(s) {uncovered!r} that "
            "the matrix columns do not cover; widen column_keys/dense axes or "
            "keep the relation frame"
        )


def _ensure_unique_pairs(
    relation: pd.DataFrame,
    row_keys: list[Any],
    column_key: str,
) -> None:
    pair_cols = [*row_keys, column_key]
    duplicates = relation.duplicated(subset=pair_cols, keep=False)
    if duplicates.any():
        duplicate_rows = relation.loc[duplicates, pair_cols].to_dict(orient="records")
        raise ValueError(f"Duplicate xref row/column pairs: {duplicate_rows!r}")


def _ordered_row_identities(relation: pd.DataFrame, row_keys: list[Any]) -> list[tuple[Any, ...]]:
    seen: set[tuple[Any, ...]] = set()
    ordered: list[tuple[Any, ...]] = []
    for _, row in relation.iterrows():
        identity = tuple(row[row_key] for row_key in row_keys)
        if identity in seen:
            continue
        seen.add(identity)
        ordered.append(identity)
    return ordered


def _ordered_unique(values: Iterable[Any]) -> list[Any]:
    ordered: list[Any] = []
    for value in values:
        if any(_values_equal(existing, value) for existing in ordered):
            continue
        ordered.append(value)
    return ordered


def _relation_row_identity(
    row: Any,
    row_keys: list[Any],
    *,
    normalize: bool,
) -> tuple[Any, ...]:
    if not normalize:
        return tuple(row[row_key] for row_key in row_keys)
    return tuple(_plain_axis_value(row[row_key]) for row_key in row_keys)


def _relation_column_identity(value: Any, *, normalize: bool) -> Any:
    if not normalize:
        return value
    return _plain_axis_value(value)


def _matrix_column_keys(
    frames: Mapping[str, Any],
    *,
    relation: str,
    config_id: str,
    column_key: str,
    explicit_column_keys: Iterable[Any] | None,
    dense_resolved: Mapping[str, Any],
) -> list[Any]:
    if explicit_column_keys is not None:
        configured = _as_list(explicit_column_keys, "column_keys")
        dense_columns = dense_resolved.get("column_keys")
        if dense_columns is not None and not _ordered_values_equal(configured, dense_columns):
            raise ValueError(
                "column_keys must match dense_axes.columns_from order when both are configured: "
                f"{configured!r} vs {list(dense_columns)!r}"
            )
        return configured
    if "column_keys" in dense_resolved:
        return list(dense_resolved["column_keys"])
    return _column_keys_from_meta_or_relation(
        frames,
        relation=relation,
        config_id=config_id,
        column_key=column_key,
    )


def _column_keys_from_meta_or_relation(
    frames: Mapping[str, Any],
    *,
    relation: str,
    config_id: str,
    column_key: str,
) -> list[Any]:
    config = _xref_config(frames, config_id, relation=relation)
    if isinstance(config, Mapping) and isinstance(config.get("column_keys"), list):
        return list(config["column_keys"])
    source = _require_frame(frames, relation)
    return _ordered_unique(source[column_key].tolist())


def _write_xref_meta(
    out: dict[str, Any],
    *,
    config_id: str,
    payload: dict[str, Any],
) -> None:
    meta = dict(out.get("_meta") or {})
    configs = dict(meta.get(_META_KEY) or {})
    configs[config_id] = payload
    meta[_META_KEY] = configs
    out["_meta"] = meta
