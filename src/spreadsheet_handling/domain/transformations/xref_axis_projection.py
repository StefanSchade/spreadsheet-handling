"""Flat one-level XRef axis-label projection transformations.

Slice 2 of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. These two ``Frames -> Frames``
steps swap the *axis-identity vocabulary* of a relation's axis-identity column
(default ``column_key``) without changing XRef shape conversion:

* :func:`project_axis_labels` (outbound) replaces each canonical key with its
  resolved flat one-level visible label, so an ordinary ``contract_xref`` then
  renders readable matrix headers;
* :func:`restore_axis_keys` (inbound) replaces each flat one-level visible label
  produced by ``expand_xref`` with its canonical key.

The bijection itself is owned by the accepted Slice 1 resolver
(:mod:`spreadsheet_handling.domain.transformations.xref_axis_mapping`); these
steps only substitute values through it. They compose *around* unchanged
``contract_xref`` / ``expand_xref`` and do not wrap them.

Boundaries (per the Slice 2 confirmation contract):

* flat one-level labels only -- the mapping has a single label column, so every
  resolved label tuple has arity one and is unwrapped to a flat string; the
  hierarchical tuple model is Slice 3, grouped headers are Slice 4;
* no new persisted ``_meta`` root -- the inverse resolves from live source
  frames plus explicit configuration and fails if the source frame is absent;
  existing ``_meta`` is passed through untouched (``drop_source`` contributes
  only the existing transient ``_meta.pipeline_cleanup`` drop command);
* build-then-publish failure atomicity -- the full mapping is resolved and every
  used key/label is substituted before any output frame or ``_meta`` mutation is
  published; input frames and ``_meta`` are never mutated.

Ordering note: ``order_policy`` / ``order_columns`` are forwarded to the
resolver unchanged. They affect only the resolver's internal member *order*,
which value substitution does not consume, so a projection roundtrip is
identical under ``source_row`` and ``columns`` policies. ``source_row`` order is
defined relative to the caller-supplied source-frame row order; this capability
does not define a serialized ordering contract.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.pipeline_cleanup import mark_frames_for_cleanup
from spreadsheet_handling.domain.tabular import ensure_unique_physical_column_labels

from .xref_axis_mapping import (
    AxisMappingError,
    AxisMappingIntent,
    AxisOrderPolicy,
    resolve_axis_mapping,
)

Frames = dict[str, Any]


def _require_name(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise AxisMappingError(f"{field_name} must be a non-empty string")
    return value


def _order_policy(value: Any) -> AxisOrderPolicy:
    if type(value) is AxisOrderPolicy:
        return value
    if type(value) is str:
        try:
            return AxisOrderPolicy(value)
        except ValueError:
            pass
    raise AxisMappingError(
        "order_policy must be 'source_row' or 'columns' "
        "(or an AxisOrderPolicy member)"
    )


def _build_intent(
    *,
    source_frame: str,
    key_column: str,
    label_column: str,
    order_policy: Any,
    order_columns: Iterable[Any],
) -> AxisMappingIntent:
    # ``label_columns`` is deliberately a one-element tuple: Slice 2 is flat
    # one-level, so the resolved label tuples all have arity one. The resolver
    # owns every value-level validation (exact strings, ordering vocabulary,
    # bijection, completeness); this boundary does not repeat it.
    return AxisMappingIntent(
        source_frame=source_frame,
        key_column=key_column,
        label_columns=(label_column,),
        order_policy=_order_policy(order_policy),
        order_columns=order_columns,
    )


def _require_relation(frames: Mapping[str, Any], relation: str) -> pd.DataFrame:
    if not isinstance(frames, Mapping):
        raise AxisMappingError("Axis projection frames must be a mapping")
    if relation not in frames:
        raise AxisMappingError(
            f"Axis projection relation frame {relation!r} was not found"
        )
    df = frames[relation]
    if not isinstance(df, pd.DataFrame):
        raise AxisMappingError(
            f"Axis projection relation frame {relation!r} must be a pandas DataFrame"
        )
    try:
        ensure_unique_physical_column_labels(df, frame_name=relation)
    except ValueError as exc:
        raise AxisMappingError(f"Invalid axis projection relation: {exc}") from None
    return df


def _prepare(
    frames: Mapping[str, Any],
    *,
    relation: str,
    output: str,
    column_key: str,
    drop_source: bool,
) -> pd.DataFrame:
    _require_name(relation, field_name="relation")
    _require_name(output, field_name="output")
    _require_name(column_key, field_name="column_key")
    if drop_source and relation == output:
        raise AxisMappingError("drop_source requires a distinct output frame")
    df = _require_relation(frames, relation)
    if column_key not in df.columns:
        raise AxisMappingError(
            f"Axis projection relation frame {relation!r} is missing axis "
            f"identity column {column_key!r}"
        )
    return df


def _publish(
    frames: Mapping[str, Any],
    df: pd.DataFrame,
    *,
    output: str,
    column_key: str,
    new_values: list[Any],
    relation: str,
    drop_source: bool,
) -> Frames:
    # Build-then-publish: ``new_values`` is fully computed by the caller before
    # anything is published. The output frame is a copy, so the input relation
    # DataFrame is never mutated, and ``dict(frames)`` shallow-copies the
    # mapping so input frames stay intact. ``mark_frames_for_cleanup`` copies
    # ``_meta`` before mutating, so the caller's ``_meta`` is untouched.
    result = df.copy()
    result[column_key] = new_values
    out: dict[str, Any] = dict(frames)
    out[output] = result
    if drop_source:
        mark_frames_for_cleanup(out, [relation])
    return out


def project_axis_labels(
    frames: Mapping[str, Any],
    *,
    relation: str,
    output: str,
    source_frame: str,
    key_column: str,
    label_column: str,
    order_policy: Any = "source_row",
    order_columns: Iterable[Any] = (),
    column_key: str = "column_key",
    drop_source: bool = False,
) -> Frames:
    """Outbound: replace canonical axis keys with flat one-level visible labels.

    Reads ``relation`` (canonical keys in its ``column_key`` column) and the
    live ``source_frame`` mapping, resolves the key/label bijection, and writes
    ``output`` with each canonical key replaced by its visible label. The
    resolver's completeness check rejects any canonical key used by the relation
    that is missing from the mapping source before any output is published.

    With ``drop_source=True`` the caller asserts the labelled output supersedes
    the canonical relation, which is marked for the orchestrator-owned final
    domain cleanup. Because this is a one-to-one column substitution, no rows or
    columns are lost, so no value-loss guard is required.
    """
    df = _prepare(
        frames,
        relation=relation,
        output=output,
        column_key=column_key,
        drop_source=drop_source,
    )
    intent = _build_intent(
        source_frame=source_frame,
        key_column=key_column,
        label_column=label_column,
        order_policy=order_policy,
        order_columns=order_columns,
    )
    used_values = df[column_key].tolist()
    # ``used_keys`` validates every value is an exact non-empty string canonical
    # key and is present in the source before projection (completeness).
    mapping = resolve_axis_mapping(frames, intent, used_keys=used_values)
    # Flat one-level: ``labels_for_key`` returns an arity-one tuple; unwrap it to
    # the single visible label string that XRef will render as a matrix header.
    new_values = [mapping.labels_for_key(value)[0] for value in used_values]
    return _publish(
        frames,
        df,
        output=output,
        column_key=column_key,
        new_values=new_values,
        relation=relation,
        drop_source=drop_source,
    )


def restore_axis_keys(
    frames: Mapping[str, Any],
    *,
    relation: str,
    output: str,
    source_frame: str,
    key_column: str,
    label_column: str,
    order_policy: Any = "source_row",
    order_columns: Iterable[Any] = (),
    column_key: str = "column_key",
    drop_source: bool = False,
) -> Frames:
    """Inbound: replace flat one-level visible labels with canonical axis keys.

    Reads ``relation`` (visible labels in its ``column_key`` column, typically
    produced by ``expand_xref``) and the live ``source_frame`` mapping, resolves
    the bijection, and writes ``output`` with each visible label replaced by its
    canonical key. A visible label that does not resolve to a canonical key (an
    unknown label) fails before any output is published.

    With ``drop_source=True`` the caller asserts the restored output supersedes
    the labelled relation, which is marked for the orchestrator-owned final
    domain cleanup.
    """
    df = _prepare(
        frames,
        relation=relation,
        output=output,
        column_key=column_key,
        drop_source=drop_source,
    )
    intent = _build_intent(
        source_frame=source_frame,
        key_column=key_column,
        label_column=label_column,
        order_policy=order_policy,
        order_columns=order_columns,
    )
    # Inbound uses the label side as the "used" vocabulary, so completeness is
    # enforced per value by ``key_for_labels`` rather than through ``used_keys``.
    mapping = resolve_axis_mapping(frames, intent)
    values = df[column_key].tolist()
    # Flat one-level: wrap each visible label as a one-element tuple for exact
    # inverse lookup; ``key_for_labels`` validates arity and rejects unknowns.
    new_values = [mapping.key_for_labels((value,)) for value in values]
    return _publish(
        frames,
        df,
        output=output,
        column_key=column_key,
        new_values=new_values,
        relation=relation,
        drop_source=drop_source,
    )
