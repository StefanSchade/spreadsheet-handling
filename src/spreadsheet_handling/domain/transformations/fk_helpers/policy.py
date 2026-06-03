"""Resolution of FK helper policies from ``_meta`` for primitive consumers.

Primitives consume the v2 relation policy under
``_meta.helper_policies.fk.relations`` (schema_version 2). Convention-driven
relation inference is owned by the ``infer_fk_relations`` configuration step;
primitives never re-derive FK identity from column names.

Refactored from the previous v1 consumption path by
``FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5``.
"""
from __future__ import annotations

from typing import Any

from ....core.fk import FKDef, normalize_sheet_key
from ....frame_keys import iter_data_frames

Frames = dict[str, Any]

_FK_POLICY_SCHEMA_VERSION = 2


class MissingFkRelationPolicyError(ValueError):
    """Raised when a primitive FK-helper step runs without v2 relation policy.

    Primitive steps are deterministic executors of resolved metadata. Missing
    policy is reported clearly and names the configuration / inference step
    that should have run first.
    """


def resolve_v2_fk_relations(frames: Frames) -> list[dict[str, Any]] | None:
    """Return the v2 FK relations list from ``_meta``.

    Returns ``None`` when the v2 shape is absent (no ``helper_policies.fk``
    block, missing ``schema_version``, or ``schema_version != 2``). Returns an
    empty list when the v2 block is present but declares no relations.
    """
    meta = frames.get("_meta")
    if not isinstance(meta, dict):
        return None
    helper_policies = meta.get("helper_policies")
    if not isinstance(helper_policies, dict):
        return None
    fk_root = helper_policies.get("fk")
    if not isinstance(fk_root, dict):
        return None
    if fk_root.get("schema_version") != _FK_POLICY_SCHEMA_VERSION:
        return None
    relations = fk_root.get("relations")
    if relations is None:
        return []
    if not isinstance(relations, list):
        raise ValueError(
            "Malformed `_meta.helper_policies.fk.relations`: expected a list, "
            f"got {type(relations).__name__}"
        )
    return relations


def missing_fk_policy_error(step_name: str) -> MissingFkRelationPolicyError:
    """Build a clear error pointing the caller at the producer steps."""
    return MissingFkRelationPolicyError(
        f"{step_name} requires v2 FK relation policy at "
        "`_meta.helper_policies.fk` (schema_version: 2). Run "
        "`configure_fk_helpers` (explicit configuration) or "
        "`infer_fk_relations` (heuristic inference) before "
        f"`{step_name}` to produce that policy. Convention-driven "
        "primitive inference is no longer supported."
    )


def build_v2_target_registry(
    relations: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """Derive a target-side registry and required fields from v2 relations.

    Returns a ``(registry, fields_by_target_sheet_key)`` pair. The registry
    mirrors the structure produced by ``core.fk.build_registry`` so the
    legacy ``apply_fk_helpers`` / ``build_id_value_maps`` plumbing can drive
    materialization without ever inspecting frame column names.
    """
    registry: dict[str, dict[str, Any]] = {}
    fields_by_target_sheet: dict[str, list[str]] = {}

    for relation in relations:
        target_frame = str(relation.get("target_frame", ""))
        target_key = str(relation.get("target_key", ""))
        if not target_frame or not target_key:
            raise ValueError(
                "v2 FK relation entry is missing required fields "
                "`target_frame`/`target_key`: " + repr(relation)
            )
        sheet_key = normalize_sheet_key(target_frame)
        existing = registry.get(sheet_key)
        if existing is None:
            registry[sheet_key] = {
                "sheet_name": target_frame,
                "id_field": target_key,
                # ``label_field`` is intentionally a no-op default. v2
                # relations carry per-field selection in ``helper_columns``;
                # no implicit label_field is honored.
                "label_field": target_key,
            }
        elif existing["id_field"] != target_key:
            raise ValueError(
                f"Conflicting target_key for target frame {target_frame!r}: "
                f"{existing['id_field']!r} vs {target_key!r}"
            )

        fields = fields_by_target_sheet.setdefault(sheet_key, [])
        for entry in relation.get("helper_columns") or []:
            target_field = str(entry.get("target_field", ""))
            if target_field and target_field not in fields:
                fields.append(target_field)
    return registry, fields_by_target_sheet


def iter_relation_fk_defs(
    relation: dict[str, Any],
) -> list[FKDef]:
    """Build ``FKDef`` rows describing one relation's helper columns.

    Each helper column entry yields one ``FKDef`` so existing materialization
    plumbing (``core.fk.apply_fk_helpers``) can be reused unchanged.
    """
    source_column = str(relation["source_column"])
    target_frame = str(relation["target_frame"])
    target_key = str(relation["target_key"])
    target_sheet_key = normalize_sheet_key(target_frame)
    defs: list[FKDef] = []
    for entry in relation.get("helper_columns") or []:
        helper_column = str(entry["column"])
        value_field = str(entry["target_field"])
        defs.append(
            FKDef(
                fk_column=source_column,
                id_field=target_key,
                target_sheet_key=target_sheet_key,
                helper_column=helper_column,
                value_field=value_field,
            )
        )
    return defs


def source_frame_has_column(df: Any, column: str) -> bool:
    """Return True when ``column`` appears as a first-level header on ``df``."""
    columns = getattr(df, "columns", None)
    if columns is None:
        return False
    for header in columns:
        first = header[0] if isinstance(header, tuple) else header
        if str(first) == column:
            return True
    return False


def derived_helper_columns_by_sheet(
    frames: Frames,
) -> dict[str, list[dict[str, Any]]]:
    """Return ``_meta.derived.sheets.<sheet>.helper_columns`` per sheet."""
    meta = frames.get("_meta")
    if not isinstance(meta, dict):
        return {}
    derived = meta.get("derived")
    if not isinstance(derived, dict):
        return {}
    sheets = derived.get("sheets")
    if not isinstance(sheets, dict):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for sheet_name, sheet_entry in sheets.items():
        if not isinstance(sheet_entry, dict):
            continue
        entries = sheet_entry.get("helper_columns")
        if isinstance(entries, list) and entries:
            out[str(sheet_name)] = [dict(entry) for entry in entries if isinstance(entry, dict)]
    return out


def known_data_frame_names(frames: Frames) -> set[str]:
    return {sheet_name for sheet_name, _df in iter_data_frames(frames)}
