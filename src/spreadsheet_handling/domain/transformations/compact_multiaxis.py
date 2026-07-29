"""Compact multi-axis transformations.

This module composes the generic XRef and cell-codec primitives. It keeps
matrix axes, cell codes, and optional code groups generic; domain meaning stays
outside this layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

import pandas as pd

from ._legend_blocks import _read_legend_block
from .cell_codec import decode_cell_values, encode_cell_values
from .xref_crosstable import contract_xref, expand_xref

Frames = dict[str, Any]

_META_KEY = "compact_multiaxis"
_XREF_META_KEY = "xref_crosstable"
_ABSENT = object()


def expand_compact_multiaxis(
    frames: Mapping[str, Any],
    *,
    matrix: str,
    output: str,
    row_keys: str | Iterable[Any],
    value_columns: Iterable[Any] | None = None,
    column_key: str = "column_key",
    value: str = "value",
    code: str = "code",
    group: str | None = None,
    mode: str = "whole_cell_code",
    delimiter: str = "-",
    allowed_codes: Iterable[Any] | None = None,
    allowed_tokens: Iterable[Any] | None = None,
    allowed_from_legend: str | None = None,
    code_groups: Mapping[Any, Any] | None = None,
    normalize_case: str | None = None,
    strip: bool = False,
    drop_empty: bool = True,
    dense_axes: Mapping[str, Any] | None = None,
    base_canonical_relation: str | None = None,
    name: str | None = None,
) -> Frames:
    """Expand a compact matrix into generic explicit code rows.

    ``base_canonical_relation`` is the opt-in scoped-recomposition input. It
    names a frame holding the *canonical* relation ``[*row_keys, column_key,
    code (, group)]`` (the pre-codec shape this composite produces on the
    forward path), not the compact XRef-boundary shape. When supplied, the
    composite reconstructs a *partial* spreadsheet projection without losing
    out-of-scope canonical rows by composing existing primitives:

    #. Cell Codec encode of the canonical base to the compact encoded relation
       ``[*row_keys, column_key, value]`` XRef expects, under the *same*
       effective codec configuration used for the matrix result;
    #. XRef ``base_relation`` scoped recomposition -- in-scope matrix addresses
       replace exactly the visible scope; out-of-scope base rows are preserved;
    #. Cell Codec decode of the merged compact relation back to canonical rows.

    No row-merge/dedup logic lives here: replacement, deletion, ordering, and
    ambiguity are owned by XRef; the shape transform is owned by Cell Codec.
    Omitting ``base_canonical_relation`` (the default) reproduces the pre-FTR
    full-replacement behavior byte-for-byte.
    """
    _reject_dense_axes(dense_axes)
    config_id = name or output
    row_key_cols = _as_list(row_keys, "row_keys")
    passthrough = [*row_key_cols, column_key]
    _ensure_distinct_output_columns(passthrough, code=code, group=group)

    prior_xref = _snapshot_xref_meta(frames)
    temp_relation = _temp_frame_name(frames, f"__compact_multiaxis_{config_id}_xref")

    # Scoped recomposition (opt-in): contract the canonical base with the same
    # Cell Codec configuration used for the matrix result so it reaches XRef in
    # the compact encoded-relation shape XRef owns. The temp base frame is a
    # locally-created intermediate; it never leaves this function or enters any
    # persisted metadata. When no base is supplied, ``expand_source`` is the
    # caller mapping and ``temp_base``/``base_relation`` stay ``None`` -- the
    # exact pre-FTR call.
    expand_source: Mapping[str, Any] = frames
    temp_base: str | None = None
    if base_canonical_relation is not None:
        temp_base = _temp_frame_name(
            frames, f"__compact_multiaxis_{config_id}_base"
        )
        expand_source = encode_cell_values(
            frames,
            source=base_canonical_relation,
            output=temp_base,
            group_by=passthrough,
            code=code,
            value=value,
            mode=mode,
            delimiter=delimiter,
            allowed_codes=allowed_codes,
            allowed_tokens=allowed_tokens,
            allowed_from_legend=allowed_from_legend,
            normalize_case=normalize_case,
            strip=strip,
            name=config_id,
        )

    expanded = expand_xref(
        expand_source,
        matrix=matrix,
        output=temp_relation,
        row_keys=row_key_cols,
        value_columns=value_columns,
        column_key=column_key,
        value=value,
        drop_empty=False,
        base_relation=temp_base,
        name=config_id,
    )
    decoded = decode_cell_values(
        expanded,
        source=temp_relation,
        output=output,
        value=value,
        code=code,
        passthrough_columns=passthrough,
        drop_empty=drop_empty,
        mode=mode,
        delimiter=delimiter,
        allowed_codes=allowed_codes,
        allowed_tokens=allowed_tokens,
        allowed_from_legend=allowed_from_legend,
        normalize_case=normalize_case,
        strip=strip,
        name=config_id,
    )

    out: dict[str, Any] = dict(decoded)
    out.pop(temp_relation, None)
    if temp_base is not None:
        out.pop(temp_base, None)
    if group is not None:
        out[output] = _with_group_column(
            out[output],
            code=code,
            group=group,
            meta=_meta_from_frames(frames),
            allowed_from_legend=allowed_from_legend,
            code_groups=code_groups,
            normalize_case=normalize_case,
            strip=strip,
        )

    _restore_xref_meta(out, prior_xref)
    _write_multiaxis_meta(
        out,
        config_id=config_id,
        payload={
            "operation": "expand_compact_multiaxis",
            "matrix": matrix,
            "output": output,
            "row_keys": list(row_key_cols),
            "value_columns": None if value_columns is None else list(value_columns),
            "column_key": column_key,
            "value": value,
            "code": code,
            "group": group,
            "drop_empty": bool(drop_empty),
            "base_canonical_relation": base_canonical_relation,
            **_codec_payload(
                mode=mode,
                delimiter=delimiter,
                allowed_codes=allowed_codes,
                allowed_tokens=allowed_tokens,
                allowed_from_legend=allowed_from_legend,
                code_groups=code_groups,
                normalize_case=normalize_case,
                strip=strip,
            ),
        },
    )
    return out


def contract_compact_multiaxis(
    frames: Mapping[str, Any],
    *,
    relation: str,
    output: str,
    row_keys: str | Iterable[Any],
    column_key: str = "column_key",
    code: str = "code",
    value: str = "value",
    column_keys: Iterable[Any] | None = None,
    fill_value: Any = "",
    mode: str = "whole_cell_code",
    delimiter: str = "-",
    allowed_codes: Iterable[Any] | None = None,
    allowed_tokens: Iterable[Any] | None = None,
    allowed_from_legend: str | None = None,
    canonical_order: Iterable[Any] | None = None,
    normalize_case: str | None = None,
    strip: bool = False,
    dense_axes: Mapping[str, Any] | None = None,
    name: str | None = None,
) -> Frames:
    """Contract generic explicit code rows back into a compact matrix."""
    _reject_dense_axes(dense_axes)
    config_id = name or relation
    row_key_cols = _as_list(row_keys, "row_keys")
    group_by = [*row_key_cols, column_key]

    prior_xref = _snapshot_xref_meta(frames)
    temp_relation = _temp_frame_name(frames, f"__compact_multiaxis_{config_id}_encoded")
    encoded = encode_cell_values(
        frames,
        source=relation,
        output=temp_relation,
        group_by=group_by,
        code=code,
        value=value,
        mode=mode,
        delimiter=delimiter,
        allowed_codes=allowed_codes,
        allowed_tokens=allowed_tokens,
        allowed_from_legend=allowed_from_legend,
        canonical_order=canonical_order,
        normalize_case=normalize_case,
        strip=strip,
        name=config_id,
    )
    contracted = contract_xref(
        encoded,
        relation=temp_relation,
        output=output,
        row_keys=row_key_cols,
        column_key=column_key,
        value=value,
        column_keys=column_keys,
        fill_value=fill_value,
        name=config_id,
    )

    out: dict[str, Any] = dict(contracted)
    out.pop(temp_relation, None)
    _restore_xref_meta(out, prior_xref)
    _write_multiaxis_meta(
        out,
        config_id=config_id,
        payload={
            "operation": "contract_compact_multiaxis",
            "relation": relation,
            "matrix": output,
            "row_keys": list(row_key_cols),
            "column_key": column_key,
            "code": code,
            "value": value,
            "column_keys": None if column_keys is None else list(column_keys),
            "fill_value": fill_value,
            "canonical_order": None if canonical_order is None else list(canonical_order),
            **_codec_payload(
                mode=mode,
                delimiter=delimiter,
                allowed_codes=allowed_codes,
                allowed_tokens=allowed_tokens,
                allowed_from_legend=allowed_from_legend,
                code_groups=None,
                normalize_case=normalize_case,
                strip=strip,
            ),
        },
    )
    return out


def _with_group_column(
    frame: pd.DataFrame,
    *,
    code: str,
    group: str,
    meta: Mapping[str, Any],
    allowed_from_legend: str | None,
    code_groups: Mapping[Any, Any] | None,
    normalize_case: str | None,
    strip: bool,
) -> pd.DataFrame:
    if code not in frame.columns:
        raise KeyError(f"Frame is missing code column {code!r}")
    if group in frame.columns:
        raise ValueError(f"group column {group!r} collides with an existing output column")

    lookup = _group_lookup(
        meta=meta,
        allowed_from_legend=allowed_from_legend,
        code_groups=code_groups,
        normalize_case=normalize_case,
        strip=strip,
    )
    out = frame.copy()
    out[group] = [
        lookup.get(_normalize_key(value, normalize_case=normalize_case, strip=strip), "")
        for value in out[code].tolist()
    ]
    return out


def _group_lookup(
    *,
    meta: Mapping[str, Any],
    allowed_from_legend: str | None,
    code_groups: Mapping[Any, Any] | None,
    normalize_case: str | None,
    strip: bool,
) -> dict[str, Any]:
    lookup: dict[str, Any] = {}
    if allowed_from_legend:
        for token, group_value in _legend_groups(meta, allowed_from_legend).items():
            key = _normalize_key(token, normalize_case=normalize_case, strip=strip)
            if key in lookup and lookup[key] != group_value:
                raise ValueError(f"Conflicting group value for code {key!r}")
            lookup[key] = group_value

    if code_groups:
        for token, group_value in code_groups.items():
            key = _normalize_key(token, normalize_case=normalize_case, strip=strip)
            if key in lookup and lookup[key] != group_value:
                raise ValueError(f"Conflicting group value for code {key!r}")
            lookup[key] = group_value
    return lookup


def _legend_groups(meta: Mapping[str, Any], legend_name: str) -> dict[Any, Any]:
    groups: dict[Any, Any] = {}
    for token, group_value in _read_legend_block(meta, legend_name):
        if token in groups and groups[token] != group_value:
            raise ValueError(
                f"Legend block {legend_name!r} has conflicting group values for {token!r}"
            )
        groups[token] = group_value
    return groups


def _as_list(value: str | Iterable[Any] | None, field_name: str) -> list[Any]:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, str):
        result = [value]
    else:
        result = list(value)
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    if any(isinstance(item, tuple) for item in result):
        raise ValueError(
            f"{field_name} contains tuple labels; "
            "FTR-COMPACT-MULTIAXIS first slice requires flat labels"
        )
    return result


def _ensure_distinct_output_columns(
    passthrough: Iterable[Any],
    *,
    code: str,
    group: str | None,
) -> None:
    reserved = {code}
    if group is not None:
        reserved.add(group)
    collisions = [column for column in passthrough if column in reserved]
    if collisions:
        raise ValueError(f"Output columns collide with passthrough columns: {collisions!r}")
    if group is not None and group == code:
        raise ValueError("group and code output names must differ")


def _reject_dense_axes(dense_axes: Mapping[str, Any] | None) -> None:
    if dense_axes is not None:
        raise NotImplementedError(
            "dense_axes is a future explicit reconstruction contract and is not implemented "
            "by the current compact-transform slice. Use drop_empty=False for strict "
            "matrix-shape roundtrips until dense_axes is implemented explicitly."
        )


def _normalize_key(value: Any, *, normalize_case: str | None, strip: bool) -> str:
    text = str(value)
    if strip:
        text = text.strip()
    if normalize_case == "upper":
        return text.upper()
    if normalize_case == "lower":
        return text.lower()
    return text


def _temp_frame_name(frames: Mapping[str, Any], base: str) -> str:
    candidate = base
    index = 2
    while candidate in frames:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _meta_from_frames(frames: Mapping[str, Any]) -> Mapping[str, Any]:
    meta = frames.get("_meta") if isinstance(frames, Mapping) else None
    return meta if isinstance(meta, Mapping) else {}


def _codec_payload(
    *,
    mode: str,
    delimiter: str,
    allowed_codes: Iterable[Any] | None,
    allowed_tokens: Iterable[Any] | None,
    allowed_from_legend: str | None,
    code_groups: Mapping[Any, Any] | None,
    normalize_case: str | None,
    strip: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": mode,
        "delimiter": delimiter,
        "strip": bool(strip),
    }
    if allowed_codes is not None:
        payload["allowed_codes"] = list(allowed_codes)
    if allowed_tokens is not None:
        payload["allowed_tokens"] = list(allowed_tokens)
    if allowed_from_legend is not None:
        payload["allowed_from_legend"] = allowed_from_legend
    if code_groups is not None:
        payload["code_groups"] = {
            _normalize_key(key, normalize_case=normalize_case, strip=strip): value
            for key, value in code_groups.items()
        }
    if normalize_case is not None:
        payload["normalize_case"] = normalize_case
    return payload


def _write_multiaxis_meta(
    out: dict[str, Any],
    *,
    config_id: str,
    payload: dict[str, Any],
) -> None:
    meta = dict(out.get("_meta") or {})
    configs = dict(meta.get(_META_KEY) or {})
    configs[config_id] = deepcopy(payload)
    meta[_META_KEY] = configs
    out["_meta"] = meta


def _snapshot_xref_meta(frames: Mapping[str, Any]) -> Any:
    """Copy the caller's XRef root before the composite delegates to XRef."""
    meta = frames.get("_meta")
    if not isinstance(meta, Mapping) or _XREF_META_KEY not in meta:
        return _ABSENT
    return deepcopy(meta[_XREF_META_KEY])


def _restore_xref_meta(out: dict[str, Any], prior_xref: Any) -> None:
    """Suppress the internal XRef leg by restoring the caller's prior root."""
    meta = dict(out.get("_meta") or {})
    prior_was_empty_mapping = isinstance(prior_xref, Mapping) and not prior_xref
    if prior_xref is _ABSENT or prior_was_empty_mapping:
        meta.pop(_XREF_META_KEY, None)
    else:
        meta[_XREF_META_KEY] = prior_xref
    out["_meta"] = meta
