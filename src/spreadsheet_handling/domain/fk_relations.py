"""V2 FK relation policy and the ``infer_fk_relations`` configuration step.

The v2 policy lives under the existing root ``_meta.helper_policies.fk`` and
is keyed at the relation level by ``(source_frame, source_column)``. See
``docs/technical_model/ch04_concepts/fk_helper_metadata.adoc`` and
``docs/cold_storage/backlog/ftrs_done/FTR-FK-RELATION-POLICY-MODEL-P5.adoc``.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd

from ..core.fk import normalize_sheet_key
from ..frame_keys import iter_data_frames

Frames = dict[str, Any]

SCHEMA_VERSION = 2

_DEFAULT_ID_COLUMNS: tuple[str, ...] = ("id",)
_DEFAULT_FK_PATTERNS: tuple[str, ...] = ("id_({target})",)
_DEFAULT_TARGET_LABEL_FIELDS: tuple[str, ...] = ("name", "label")
_VALID_MODES: frozenset[str] = frozenset({"naming_convention"})
_VALID_POLICIES: frozenset[str] = frozenset({"fail", "ignore"})


def infer_fk_relations(
    frames: Frames,
    *,
    mode: str = "naming_convention",
    id_columns: list[str] | None = None,
    fk_patterns: list[str] | None = None,
    target_label_fields: list[str] | None = None,
    helper_prefix: str = "_",
    on_ambiguous: str = "fail",
    on_missing_target: str = "fail",
) -> Frames:
    """Infer FK relations via bounded heuristics and write v2 policy.

    Reads current data frames, applies ``mode`` (initially only
    ``naming_convention``) to derive relation entries, and writes resolved
    v2 policy under ``_meta.helper_policies.fk`` with
    ``produced_by.step = "infer_fk_relations"`` and
    ``produced_by.mode = <mode>``.

    The step never materializes helper columns, never validates helper
    values, and never writes derived helper provenance.
    """
    _validate_inference_inputs(
        mode=mode,
        on_ambiguous=on_ambiguous,
        on_missing_target=on_missing_target,
    )

    resolved_id_columns = list(id_columns or _DEFAULT_ID_COLUMNS)
    resolved_patterns = list(fk_patterns or _DEFAULT_FK_PATTERNS)
    resolved_label_fields = list(target_label_fields or _DEFAULT_TARGET_LABEL_FIELDS)
    compiled_patterns = [_compile_fk_pattern(pat) for pat in resolved_patterns]

    data_frames: list[tuple[str, pd.DataFrame]] = list(iter_data_frames(frames))
    frame_lookup = _build_frame_lookup(data_frames)

    new_relations: list[dict[str, Any]] = []
    for source_frame, source_df in data_frames:
        for column in _first_level_columns(source_df):
            relation = _try_build_inferred_relation(
                source_frame=source_frame,
                source_column=column,
                compiled_patterns=compiled_patterns,
                frame_lookup=frame_lookup,
                resolved_id_columns=resolved_id_columns,
                resolved_label_fields=resolved_label_fields,
                helper_prefix=helper_prefix,
                mode=mode,
                on_ambiguous=on_ambiguous,
                on_missing_target=on_missing_target,
            )
            if relation is not None:
                new_relations.append(relation)

    return apply_v2_relations(frames, new_relations)


def _validate_inference_inputs(
    *,
    mode: str,
    on_ambiguous: str,
    on_missing_target: str,
) -> None:
    if mode not in _VALID_MODES:
        raise ValueError(
            f"infer_fk_relations: unknown mode {mode!r}; "
            f"supported modes: {sorted(_VALID_MODES)}"
        )
    if on_ambiguous not in _VALID_POLICIES:
        raise ValueError(
            f"infer_fk_relations: on_ambiguous must be one of "
            f"{sorted(_VALID_POLICIES)}, got {on_ambiguous!r}"
        )
    if on_missing_target not in _VALID_POLICIES:
        raise ValueError(
            f"infer_fk_relations: on_missing_target must be one of "
            f"{sorted(_VALID_POLICIES)}, got {on_missing_target!r}"
        )


def _try_build_inferred_relation(
    *,
    source_frame: str,
    source_column: Any,
    compiled_patterns: list[re.Pattern[str]],
    frame_lookup: dict[str, list[tuple[str, pd.DataFrame]]],
    resolved_id_columns: list[str],
    resolved_label_fields: list[str],
    helper_prefix: str,
    mode: str,
    on_ambiguous: str,
    on_missing_target: str,
) -> dict[str, Any] | None:
    target_token = _match_fk_pattern(source_column, compiled_patterns)
    if target_token is None:
        return None

    matches = frame_lookup.get(normalize_sheet_key(target_token), [])
    if not matches:
        if on_missing_target == "fail":
            raise ValueError(
                f"infer_fk_relations: source column {source_column!r} on frame "
                f"{source_frame!r} references target {target_token!r}, "
                "but no matching data frame was found"
            )
        return None
    if len(matches) > 1:
        if on_ambiguous == "fail":
            candidates = sorted(name for name, _df in matches)
            raise ValueError(
                f"infer_fk_relations: source column {source_column!r} on frame "
                f"{source_frame!r} is ambiguous; target token "
                f"{target_token!r} matched multiple frames {candidates!r}"
            )
        return None

    target_frame_name, target_df = matches[0]
    target_key = _pick_first_present(resolved_id_columns, target_df.columns)
    if target_key is None:
        if on_missing_target == "fail":
            raise ValueError(
                f"infer_fk_relations: target frame {target_frame_name!r} "
                f"has no id column from {resolved_id_columns!r}"
            )
        return None

    helper_fields = [
        str(field)
        for field in resolved_label_fields
        if field in list(target_df.columns) and str(field) != str(target_key)
    ]
    helper_columns = [
        {
            "column": f"{helper_prefix}{target_frame_name}_{field}",
            "target_field": field,
        }
        for field in helper_fields
    ]

    return build_v2_relation(
        source_frame=source_frame,
        source_column=str(source_column),
        target_frame=target_frame_name,
        target_key=str(target_key),
        helper_fields=helper_fields,
        helper_columns=helper_columns,
        helper_prefix=helper_prefix,
        produced_by_step="infer_fk_relations",
        produced_by_mode=mode,
    )


def apply_v2_relations(
    frames: Frames,
    new_relations: Iterable[dict[str, Any]],
) -> Frames:
    """Merge ``new_relations`` into ``_meta.helper_policies.fk`` (v2 shape).

    Sets ``schema_version: 2`` and stores ``relations`` as a deterministic
    list sorted by ``(source_frame, source_column)``.

    Conflict rules for entries that collide on the same relation key:

    * cross-producer (different ``produced_by.step``) -> raise;
    * same producer, semantically identical relation -> accept idempotently
      (no-op overwrite);
    * same producer, any meaningful field differs -> raise.

    Meaningful fields cover the whole v2 relation entry, including
    ``target_frame``, ``target_key``, ``helper_fields``, ``helper_columns``,
    ``helper_prefix``, and ``produced_by.mode``.
    """
    out = dict(frames)
    meta = dict(out.get("_meta") or {})
    helper_policies = dict(meta.get("helper_policies") or {})
    fk_root = dict(helper_policies.get("fk") or {})

    relations_by_key: dict[tuple[str, str], dict[str, Any]] = {
        _relation_key(relation): relation
        for relation in (fk_root.get("relations") or [])
    }

    for relation in new_relations:
        key = _relation_key(relation)
        prior = relations_by_key.get(key)
        if prior is not None:
            _assert_no_relation_conflict(key, prior, relation)
        relations_by_key[key] = relation

    fk_root["schema_version"] = SCHEMA_VERSION
    fk_root["relations"] = [
        relations_by_key[key] for key in sorted(relations_by_key.keys())
    ]
    helper_policies["fk"] = fk_root
    meta["helper_policies"] = helper_policies
    out["_meta"] = meta
    return out


def _relation_key(relation: dict[str, Any]) -> tuple[str, str]:
    return (
        str(relation.get("source_frame")),
        str(relation.get("source_column")),
    )


def _assert_no_relation_conflict(
    key: tuple[str, str],
    prior: dict[str, Any],
    new: dict[str, Any],
) -> None:
    prior_step = str((prior.get("produced_by") or {}).get("step"))
    new_step = str((new.get("produced_by") or {}).get("step"))
    if prior_step and new_step and prior_step != new_step:
        raise ValueError(
            f"FK relation {key!r} is already produced by {prior_step!r}; "
            f"refusing overwrite by {new_step!r}. A relation key may be "
            "produced by at most one configuration step in a single "
            "pipeline run."
        )
    if prior == new:
        return
    raise ValueError(
        f"FK relation {key!r} would be overwritten by producer {new_step!r} "
        f"with a different relation body; same-producer rewrites are only "
        f"accepted when semantically identical. Existing: {prior!r}; new: "
        f"{new!r}."
    )


def build_v2_relation(
    *,
    source_frame: str,
    source_column: str,
    target_frame: str,
    target_key: str,
    helper_fields: list[str],
    helper_columns: list[dict[str, str]],
    helper_prefix: str,
    produced_by_step: str,
    produced_by_mode: str,
) -> dict[str, Any]:
    """Build a canonical v2 FK relation entry.

    Public so that any configuration step writing into
    ``_meta.helper_policies.fk.relations`` constructs the same shape (which
    ``apply_v2_relations`` compares for same-producer idempotency).
    """
    return {
        "source_frame": source_frame,
        "source_column": source_column,
        "target_frame": target_frame,
        "target_key": target_key,
        "helper_fields": list(helper_fields),
        "helper_columns": [
            {"column": str(entry["column"]), "target_field": str(entry["target_field"])}
            for entry in helper_columns
        ],
        "helper_prefix": helper_prefix,
        "produced_by": {"step": produced_by_step, "mode": produced_by_mode},
    }


def _compile_fk_pattern(pattern: str) -> re.Pattern[str]:
    placeholder = "{target}"
    if placeholder not in pattern:
        raise ValueError(
            f"infer_fk_relations: fk_patterns entry {pattern!r} must contain "
            f"the placeholder {placeholder!r}"
        )
    head, _, tail = pattern.partition(placeholder)
    return re.compile(
        rf"^{re.escape(head)}(?P<target>[^)]+){re.escape(tail)}$"
    )


def _match_fk_pattern(
    column: Any,
    compiled_patterns: list[re.Pattern[str]],
) -> str | None:
    if not isinstance(column, str):
        return None
    for compiled in compiled_patterns:
        match = compiled.match(column)
        if match is not None:
            return match.group("target")
    return None


def _build_frame_lookup(
    data_frames: list[tuple[str, pd.DataFrame]],
) -> dict[str, list[tuple[str, pd.DataFrame]]]:
    lookup: dict[str, list[tuple[str, pd.DataFrame]]] = {}
    for name, df in data_frames:
        normalized = normalize_sheet_key(name)
        lookup.setdefault(normalized, []).append((name, df))
    return lookup


def _pick_first_present(
    candidates: list[str],
    columns: Iterable[Any],
) -> str | None:
    column_set = {str(column) for column in columns}
    for candidate in candidates:
        name = str(candidate)
        if name in column_set:
            return name
    return None


def _first_level_columns(df: pd.DataFrame) -> list[Any]:
    return [
        column[0] if isinstance(column, tuple) else column
        for column in df.columns
    ]
