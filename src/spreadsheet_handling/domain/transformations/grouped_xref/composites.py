"""Public grouped-XRef composites for GX-2.

GX-2 of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. Two directional ``Frames -> Frames``
composites project a canonical relation onto a *grouped* matrix (multi-level
visible label tuples on the dynamic column headers) and back, composing *around*
unchanged XRef:

* :func:`contract_grouped_xref` (forward) -- unchanged ``contract_xref`` ->
  private flat canonical-string matrix -> GX-1 ``build_grouped_header`` ->
  a :class:`GroupedMatrix` carrier published under ``output``;
* :func:`expand_grouped_xref` (inverse) -- GX-1 ``restore_flat_matrix`` ->
  private flat canonical-string matrix -> unchanged ``expand_xref`` ->
  canonical relation.

The bijection is owned by the accepted Slice 1 resolver; the header projection by
the accepted GX-1 primitives; relation/matrix shape by unchanged XRef. GX-2 owns
only composition, the trusted ``GroupedMatrix`` pairing, and single mapping
resolution.

Contract highlights (per the GX-2 confirmation review):

* *Runtime representation* -- the flat DataFrame and its ``GroupedHeader`` travel
  as one Frames value, the :class:`GroupedMatrix` carrier. Public construction
  and inverse use both prove their exact semantic pairing under the live mapping.
* *Mapping resolution* -- resolved exactly once per call and handed to GX-1; the
  forward enforces ``used_keys`` completeness against the matrix's dynamic
  headers; the inverse relies on exact ``key_for_labels``. Nothing is persisted.
* *Metadata* -- ``xref_config_id`` forwards as unchanged XRef's ``name`` and
  selects its ``_meta.xref_crosstable`` entry. YAML ``name`` remains the generic
  pipeline step name; grouped-XRef adds no metadata root.
* *Atomicity* -- ``contract_xref`` / ``expand_xref`` each return copied Frames,
  so a failure after the wrapped call and before grouped publication discards the
  interim copy and leaves caller Frames, ``_meta``, and cleanup commands
  unchanged. No private frame name is ever introduced.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from spreadsheet_handling.domain.transformations.xref_crosstable import (
    contract_xref,
    expand_xref,
)

from ..xref_axis_mapping import (
    AxisMappingIntent,
    AxisOrderPolicy,
    resolve_axis_mapping,
)

from .matrix import (
    GroupedMatrix,
    GroupedXrefError,
    _validate_grouped_matrix_pair,
    grouped_matrix_from_canonical,
)
from .projection import build_grouped_header, restore_flat_matrix

Frames = dict[str, Any]


def _require_frames(frames: Any) -> Mapping[str, Any]:
    if not isinstance(frames, Mapping):
        raise GroupedXrefError("Grouped XRef frames must be a mapping")
    return frames


def _require_name(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise GroupedXrefError(f"{field_name} must be a non-empty string")
    return value


def _require_optional_name(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_name(value, field_name=field_name)


def _order_policy(value: Any) -> AxisOrderPolicy:
    if type(value) is AxisOrderPolicy:
        return value
    if type(value) is str:
        try:
            return AxisOrderPolicy(value)
        except ValueError:
            pass
    raise GroupedXrefError(
        "order_policy must be 'source_row' or 'columns' "
        "(or an AxisOrderPolicy member)"
    )


def _build_intent(
    *,
    source_frame: str,
    key_column: str,
    label_columns: Iterable[str],
    order_policy: Any,
    order_columns: Iterable[Any],
) -> AxisMappingIntent:
    # ``label_columns`` is arity N (top -> leaf), the grouped generalization of
    # Slice 2's one-element intent. The resolver owns every value-level
    # validation (exact strings, ordering vocabulary, bijection, completeness);
    # the ``AxisMappingIntent`` constructor owns configured-field shape. This
    # boundary repeats neither -- it only maps a raw iterable into the tuple the
    # frozen intent expects, translating shape errors into ``GroupedXrefError``.
    if isinstance(label_columns, (str, bytes)):
        raise GroupedXrefError(
            "label_columns must be an ordered sequence of source label columns"
        )
    try:
        owned_labels = tuple(label_columns)
    except TypeError:
        raise GroupedXrefError(
            "label_columns must be an ordered sequence of source label columns"
        ) from None
    # Value-level shape (empty labels, non-string configured fields, order-policy
    # vs order-columns coherence) is owned by ``AxisMappingIntent`` and surfaces
    # as ``AxisMappingError``; this composite does not wrap that domain failure.
    return AxisMappingIntent(
        source_frame=source_frame,
        key_column=key_column,
        label_columns=owned_labels,
        order_policy=_order_policy(order_policy),
        order_columns=order_columns,
    )


def _owned_row_keys(row_keys: str | Iterable[Any]) -> tuple[Any, ...]:
    """Own one reusable declaration without duplicating XRef semantics."""
    if isinstance(row_keys, str):
        return (row_keys,)
    if isinstance(row_keys, (bytes, bytearray)):
        raise GroupedXrefError("row_keys must be a string or a sequence of strings")
    try:
        return tuple(row_keys)
    except TypeError:
        raise GroupedXrefError(
            "row_keys must be a string or a sequence of strings"
        ) from None


def _dynamic_headers(frame: pd.DataFrame, row_keys: tuple[Any, ...]) -> list[Any]:
    # The wrapped XRef call has already narrowed this exact owned declaration
    # and the physical matrix headers to unique non-empty strings.
    row_key_set = frozenset(row_keys)
    return [label for label in frame.columns if label not in row_key_set]


def contract_grouped_xref(
    frames: Mapping[str, Any],
    *,
    relation: str,
    output: str,
    row_keys: str | Iterable[Any],
    source_frame: str,
    key_column: str,
    label_columns: Iterable[str],
    column_key: str = "column_key",
    value: str = "value",
    column_keys: Iterable[Any] | None = None,
    dense_axes: Mapping[str, Any] | None = None,
    fill_value: Any = "",
    level_names: Iterable[str] | None = None,
    order_policy: Any = "source_row",
    order_columns: Iterable[Any] = (),
    drop_source: bool = False,
    xref_config_id: str | None = None,
) -> Frames:
    """Forward: contract a canonical relation into a grouped-matrix carrier.

    Composes unchanged ``contract_xref`` with GX-1 under one live mapping, then
    publishes a validated carrier. ``xref_config_id`` selects XRef metadata;
    YAML ``name`` remains the pipeline step name. Publication is atomic.
    """
    _require_frames(frames)
    _require_name(relation, field_name="relation")
    _require_name(output, field_name="output")
    _require_name(column_key, field_name="column_key")
    config_id = _require_optional_name(
        xref_config_id,
        field_name="xref_config_id",
    )
    if drop_source and relation == output:
        raise GroupedXrefError("drop_source requires a distinct output frame")
    owned_row_keys = _owned_row_keys(row_keys)
    intent = _build_intent(
        source_frame=source_frame,
        key_column=key_column,
        label_columns=label_columns,
        order_policy=order_policy,
        order_columns=order_columns,
    )
    # ``contract_xref`` returns a *copied* Frames mapping; the caller's frames and
    # ``_meta`` stay untouched until this composite publishes on success.
    interim = contract_xref(
        frames,
        relation=relation,
        output=output,
        row_keys=owned_row_keys,
        column_key=column_key,
        value=value,
        column_keys=column_keys,
        fill_value=fill_value,
        dense_axes=dense_axes,
        drop_source=drop_source,
        name=config_id,
    )
    flat = interim[output]
    # The flat matrix is a component of the grouped representation, never a
    # separately addressable published frame. ``used_keys`` are exactly the
    # dynamic canonical headers that become grouped columns, giving the tightest
    # completeness check owned by this composite (GX1-A-M1).
    used_keys = _dynamic_headers(flat, owned_row_keys)
    mapping = resolve_axis_mapping(frames, intent, used_keys=used_keys)
    header = build_grouped_header(
        flat,
        row_keys=owned_row_keys,
        mapping=mapping,
        level_names=level_names,
    )
    out: dict[str, Any] = dict(interim)
    out[output] = grouped_matrix_from_canonical(
        flat,
        header,
        mapping=mapping,
    )
    return out


def expand_grouped_xref(
    frames: Mapping[str, Any],
    *,
    matrix: str,
    output: str,
    row_keys: str | Iterable[Any],
    source_frame: str,
    key_column: str,
    label_columns: Iterable[str],
    column_key: str = "column_key",
    value: str = "value",
    value_columns: Iterable[Any] | None = None,
    base_relation: str | None = None,
    order_policy: Any = "source_row",
    order_columns: Iterable[Any] = (),
    drop_source: bool = False,
    xref_config_id: str | None = None,
) -> Frames:
    """Inverse: expand a grouped-matrix carrier into a canonical relation.

    Requires ``frames[matrix]`` to be a :class:`GroupedMatrix` built through the
    validated canonical factory. The current frame/header pair is revalidated
    under the live mapping before restoration, catching post-construction column
    mutation and stale or foreign pairing.
    Resolves once, restores through GX-1, locally rebinds the real ``matrix``
    name, and runs unchanged ``expand_xref`` without a private frame. The carrier
    is preserved unless ``drop_source`` marks it for final cleanup.
    """
    _require_frames(frames)
    _require_name(matrix, field_name="matrix")
    _require_name(output, field_name="output")
    config_id = _require_optional_name(
        xref_config_id,
        field_name="xref_config_id",
    )
    if drop_source and matrix == output:
        raise GroupedXrefError("drop_source requires a distinct output frame")
    owned_row_keys = _owned_row_keys(row_keys)
    if matrix not in frames:
        raise GroupedXrefError(f"Grouped matrix frame {matrix!r} was not found")
    grouped = frames[matrix]
    if type(grouped) is not GroupedMatrix:
        raise GroupedXrefError(
            f"Grouped matrix frame {matrix!r} must be a GroupedMatrix carrier "
            "produced by contract_grouped_xref"
        )
    intent = _build_intent(
        source_frame=source_frame,
        key_column=key_column,
        label_columns=label_columns,
        order_policy=order_policy,
        order_columns=order_columns,
    )
    # Resolve once from the live source; ``restore_flat_matrix`` rejects unknown,
    # wrong-arity, incomplete, or duplicate visible tuples via ``key_for_labels``.
    mapping = resolve_axis_mapping(frames, intent)
    _validate_grouped_matrix_pair(grouped, mapping=mapping)
    flat = restore_flat_matrix(grouped.frame, grouped.header, mapping=mapping)
    # Rebind the *real* ``matrix`` name locally to the unwrapped flat DataFrame:
    # ``expand_xref`` then reads a flat matrix under the public name and never
    # sees a private frame name in its output or ``_meta``.
    interim: dict[str, Any] = dict(frames)
    interim[matrix] = flat
    result = expand_xref(
        interim,
        matrix=matrix,
        output=output,
        row_keys=owned_row_keys,
        value_columns=value_columns,
        column_key=column_key,
        value=value,
        base_relation=base_relation,
        drop_source=drop_source,
        name=config_id,
    )
    if not drop_source:
        # Keep the grouped representation under ``matrix`` (the local rebinding to
        # the bare flat frame was only for the wrapped ``expand_xref`` read).
        result[matrix] = grouped
    return result


__all__ = [
    "contract_grouped_xref",
    "expand_grouped_xref",
]
