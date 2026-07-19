from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from .meta_refs import (
    build_sheet_resolver,
    contains_structured_reference,
    is_known_schema_maintenance_root,
    is_out_of_scope_root,
    reference_root_for_blocked_name,
    resolve_sheet,
)
from .model import (
    FrameChange,
    Frames,
    MetadataReferenceChange,
    ReferenceAction,
    ReferenceRoot,
    SchemaMaintenanceFailure,
    SchemaMaintenanceReport,
    SchemaMaintenanceRequest,
    SchemaMaintenanceResult,
    SchemaOperationKind,
)


def apply_metadata_rules(
    *,
    original_frames: Frames,
    proposed_frames: Frames,
    request: SchemaMaintenanceRequest,
    frame_changes: tuple[FrameChange, ...],
) -> SchemaMaintenanceResult:
    meta = original_frames.get("_meta")
    if meta is None:
        return _result(proposed_frames, request, frame_changes, (), ())
    if not isinstance(meta, Mapping):
        return _blocked(
            original_frames,
            request,
            frame_changes,
            (),
            (
                _failure(
                    "malformed_meta",
                    "_meta must be a mapping for schema maintenance",
                    request.target_frame,
                    request.source_column,
                    "_meta",
                ),
            ),
        )

    affected_column = _affected_column(request)
    updated_meta = deepcopy(dict(meta))
    metadata_changes: list[MetadataReferenceChange] = []
    failures: list[SchemaMaintenanceFailure] = []

    if "derived" in meta:
        metadata_changes.append(
            _change(
                ReferenceRoot.DERIVED,
                "derived",
                ReferenceAction.IGNORED_DERIVED,
                request.target_frame,
                affected_column,
                "_meta.derived is ignored for schema maintenance decisions",
            )
        )

    if affected_column is None:
        return _result(_with_meta_if_changed(proposed_frames, updated_meta, False), request, frame_changes, tuple(metadata_changes), ())

    resolver = build_sheet_resolver(meta, request.target_frame)
    _handle_constraints(updated_meta, resolver, request, metadata_changes, failures)
    _handle_sheets(updated_meta, resolver, request, metadata_changes, failures)
    _handle_helper_policies(updated_meta, request, metadata_changes, failures)
    _handle_xref_crosstable(updated_meta, request, metadata_changes, failures)
    _handle_workbook_view(updated_meta, failures)
    _handle_blocked_roots(meta, request, metadata_changes, failures)
    _handle_plugin_roots(meta, request, metadata_changes, failures)

    if failures:
        return _blocked(
            original_frames,
            request,
            frame_changes,
            tuple(metadata_changes),
            tuple(failures),
        )

    meta_changed = updated_meta != dict(meta)
    return _result(
        _with_meta_if_changed(proposed_frames, updated_meta, meta_changed),
        request,
        frame_changes,
        tuple(metadata_changes),
        (),
    )


def _handle_constraints(
    meta: dict[str, Any],
    resolver: Mapping[str, Any],
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    if "constraints" not in meta:
        return
    constraints = meta["constraints"]
    if not _is_sequence(constraints):
        failures.append(_malformed("constraints", "_meta.constraints must be a list", request))
        return

    kept: list[Any] = []
    changed = False
    for index, entry in enumerate(constraints):
        path = f"constraints[{index}]"
        if not isinstance(entry, Mapping):
            failures.append(_malformed(path, f"_meta.{path} must be a mapping", request))
            kept.append(entry)
            continue
        column = entry.get("column")
        if column != _affected_column(request):
            kept.append(entry)
            continue

        resolution = resolve_sheet(resolver, entry.get("sheet"))
        if resolution.ambiguous or resolution.frame is None:
            failures.append(_ambiguous(path, request, column))
            kept.append(entry)
            continue
        if resolution.frame != request.target_frame:
            kept.append(entry)
            continue

        if request.kind == SchemaOperationKind.RENAME_COLUMN:
            updated = dict(entry)
            updated["column"] = request.target_column
            kept.append(updated)
            changed = True
            changes.append(
                _change(
                    ReferenceRoot.CONSTRAINTS,
                    f"{path}.column",
                    ReferenceAction.UPDATED,
                    request.target_frame,
                    str(column),
                    f"Renamed constraint column to {request.target_column!r}",
                )
            )
        elif request.kind == SchemaOperationKind.DROP_COLUMN and request.prune:
            changed = True
            changes.append(
                _change(
                    ReferenceRoot.CONSTRAINTS,
                    path,
                    ReferenceAction.PRUNED,
                    request.target_frame,
                    str(column),
                    "Pruned constraint referencing dropped column",
                )
            )
        elif request.kind == SchemaOperationKind.DROP_COLUMN:
            failures.append(_blocked_reference(ReferenceRoot.CONSTRAINTS, path, request, str(column)))
            kept.append(entry)
        else:
            kept.append(entry)

    if changed:
        meta["constraints"] = kept


def _handle_sheets(
    meta: dict[str, Any],
    resolver: Mapping[str, Any],
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    if "sheets" not in meta:
        return
    sheets = meta["sheets"]
    if not isinstance(sheets, Mapping):
        failures.append(_malformed("sheets", "_meta.sheets must be a mapping", request))
        return

    updated_sheets = dict(sheets)
    for sheet_name, entry in sheets.items():
        path = f"sheets.{sheet_name}"
        if not isinstance(entry, Mapping):
            failures.append(_malformed(path, f"_meta.{path} must be a mapping", request))
            continue
        resolution = resolve_sheet(resolver, sheet_name)
        updated_entry = dict(entry)
        entry_changed = False
        entry_changed |= _handle_column_list(
            owner=updated_entry,
            key="helper_columns",
            root=ReferenceRoot.SHEETS,
            path=f"{path}.helper_columns",
            resolution=resolution,
            request=request,
            changes=changes,
            failures=failures,
        )
        protection = updated_entry.get("protection")
        if isinstance(protection, Mapping):
            updated_protection = dict(protection)
            protection_changed = _handle_column_list(
                owner=updated_protection,
                key="editable_columns",
                root=ReferenceRoot.SHEETS,
                path=f"{path}.protection.editable_columns",
                resolution=resolution,
                request=request,
                changes=changes,
                failures=failures,
            )
            if protection_changed:
                updated_entry["protection"] = updated_protection
                entry_changed = True
        elif protection is not None:
            failures.append(
                _malformed(
                    f"{path}.protection",
                    f"_meta.{path}.protection must be a mapping",
                    request,
                )
            )
        if entry_changed:
            updated_sheets[sheet_name] = updated_entry

    meta["sheets"] = updated_sheets


def _handle_column_list(
    *,
    owner: dict[str, Any],
    key: str,
    root: ReferenceRoot,
    path: str,
    resolution: Any,
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> bool:
    if key not in owner:
        return False
    value = owner[key]
    if not _is_sequence(value):
        failures.append(_malformed(path, f"_meta.{path} must be a list", request))
        return False
    affected = _affected_column(request)
    if affected not in value:
        return False
    if resolution.ambiguous or resolution.frame is None:
        failures.append(_ambiguous(path, request, affected))
        return False
    if resolution.frame != request.target_frame:
        return False

    if request.kind == SchemaOperationKind.RENAME_COLUMN:
        owner[key] = [request.target_column if column == affected else column for column in value]
        changes.append(
            _change(
                root,
                path,
                ReferenceAction.UPDATED,
                request.target_frame,
                affected,
                f"Renamed metadata column to {request.target_column!r}",
            )
        )
        return True
    if request.kind == SchemaOperationKind.DROP_COLUMN and request.prune:
        owner[key] = [column for column in value if column != affected]
        changes.append(
            _change(
                root,
                path,
                ReferenceAction.PRUNED,
                request.target_frame,
                affected,
                "Pruned metadata column reference",
            )
        )
        return True
    if request.kind == SchemaOperationKind.DROP_COLUMN:
        failures.append(_blocked_reference(root, path, request, affected))
    return False


def _handle_helper_policies(
    meta: dict[str, Any],
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    helper_policies = meta.get("helper_policies")
    if helper_policies is None:
        return
    if not isinstance(helper_policies, Mapping):
        failures.append(_malformed("helper_policies", "_meta.helper_policies must be a mapping", request))
        return
    updated_helper_policies = dict(helper_policies)
    _handle_fk_policies(updated_helper_policies, request, changes, failures)
    _handle_lookup_policies(updated_helper_policies, request, changes, failures)
    _scan_unhandled_helper_policy_subtrees(helper_policies, request, changes, failures)
    meta["helper_policies"] = updated_helper_policies


def _handle_fk_policies(
    helper_policies: dict[str, Any],
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    fk = helper_policies.get("fk")
    if fk is None:
        return
    if not isinstance(fk, Mapping):
        failures.append(_malformed("helper_policies.fk", "_meta.helper_policies.fk must be a mapping", request))
        return

    updated_fk = dict(fk)
    relations = updated_fk.get("relations")
    if relations is not None:
        if not _is_sequence(relations):
            failures.append(
                _malformed(
                    "helper_policies.fk.relations",
                    "_meta.helper_policies.fk.relations must be a list",
                    request,
                )
            )
        else:
            updated_fk["relations"] = _handle_fk_relations(relations, request, changes, failures)

    # The legacy v1 per-target FK helper dict is no longer produced
    # (FK Helper Slice 2: v1 retirement), so there is no residual v1 shape
    # to block on rename/drop here. Only the durable v2 `relations` model is
    # maintained, by `_handle_fk_relations` above.
    helper_policies["fk"] = updated_fk


def _handle_lookup_policies(
    helper_policies: dict[str, Any],
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    lookup = helper_policies.get("lookup")
    if lookup is None:
        return
    if not isinstance(lookup, Mapping):
        failures.append(
            _malformed("helper_policies.lookup", "_meta.helper_policies.lookup must be a mapping", request)
        )
        return

    # A lookup policy is keyed by its lookup frame, and every column field in
    # the entry names a column of that frame (validated by
    # configure_lookup_helpers), so only the target frame's entry is affected.
    entry = lookup.get(request.target_frame)
    if entry is None:
        return
    path = f"helper_policies.lookup.{request.target_frame}"
    if not isinstance(entry, Mapping):
        failures.append(_malformed(path, f"_meta.{path} must be a mapping", request))
        return

    if request.kind == SchemaOperationKind.RENAME_COLUMN:
        updated_entry = _rename_lookup_policy_columns(entry, path, request, changes, failures)
        updated_lookup = dict(lookup)
        updated_lookup[request.target_frame] = updated_entry
        helper_policies["lookup"] = updated_lookup
    elif request.kind == SchemaOperationKind.DROP_COLUMN:
        _block_lookup_drop_if_referenced(entry, path, request, changes, failures)


_HANDLED_HELPER_POLICY_SUBTREES = frozenset({"fk", "lookup"})


def _scan_unhandled_helper_policy_subtrees(
    helper_policies: Mapping[str, Any],
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    """Block on conventional references in helper_policies subtrees we do not maintain.

    ``helper_policies`` is a supported root and therefore exempt from the
    unknown-root scan, which previously exempted *every* subtree - the
    escape class behind GAP-META-REF-CONVENTION-ESCAPE (Review 005 Slice 1c).
    Subtrees other than the explicitly maintained ``fk`` and ``lookup`` get
    the same convention scan as unknown plugin roots: a structured
    frame+column reference to the affected column blocks the operation
    instead of silently dangling.
    """
    affected = _affected_column(request)
    if affected is None:
        return
    for name, value in helper_policies.items():
        if name in _HANDLED_HELPER_POLICY_SUBTREES:
            continue
        if contains_structured_reference(value, request.target_frame, affected):
            path = f"helper_policies.{name}"
            changes.append(
                _change(
                    ReferenceRoot.UNKNOWN_PLUGIN,
                    path,
                    ReferenceAction.BLOCKED,
                    request.target_frame,
                    affected,
                    "Unmaintained helper_policies subtree references the affected column "
                    "and is not rewritten",
                )
            )
            failures.append(
                _blocked_reference(ReferenceRoot.UNKNOWN_PLUGIN, path, request, affected)
            )


def _rename_lookup_policy_columns(
    entry: Mapping[str, Any],
    path: str,
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> dict[str, Any]:
    affected = _affected_column(request)
    updated = dict(entry)

    key = entry.get("key")
    if key is not None:
        if isinstance(key, str):
            if key == affected:
                updated["key"] = request.target_column
                changes.append(_lookup_updated(f"{path}.key", request, affected))
        elif _is_sequence(key):
            if affected in key:
                updated["key"] = [
                    request.target_column if column == affected else column for column in key
                ]
                changes.append(_lookup_updated(f"{path}.key", request, affected))
        else:
            failures.append(
                _malformed(f"{path}.key", f"_meta.{path}.key must be a string or list", request)
            )

    for field in ("allowed_helpers", "default_helpers"):
        value = entry.get(field)
        if value is None:
            continue
        if not _is_sequence(value):
            failures.append(_malformed(f"{path}.{field}", f"_meta.{path}.{field} must be a list", request))
            continue
        if affected in value:
            updated[field] = [
                request.target_column if column == affected else column for column in value
            ]
            changes.append(_lookup_updated(f"{path}.{field}", request, affected))

    order = entry.get("order")
    if order is not None:
        if not isinstance(order, Mapping):
            failures.append(_malformed(f"{path}.order", f"_meta.{path}.order must be a mapping", request))
        else:
            sort_by = order.get("sort_by")
            if sort_by is None:
                pass
            elif isinstance(sort_by, str):
                if sort_by == affected:
                    updated_order = dict(order)
                    updated_order["sort_by"] = request.target_column
                    updated["order"] = updated_order
                    changes.append(_lookup_updated(f"{path}.order.sort_by", request, affected))
            elif _is_sequence(sort_by):
                if affected in sort_by:
                    updated_order = dict(order)
                    updated_order["sort_by"] = [
                        request.target_column if column == affected else column
                        for column in sort_by
                    ]
                    updated["order"] = updated_order
                    changes.append(_lookup_updated(f"{path}.order.sort_by", request, affected))
            else:
                failures.append(
                    _malformed(
                        f"{path}.order.sort_by",
                        f"_meta.{path}.order.sort_by must be a string or list",
                        request,
                    )
                )
    return updated


def _block_lookup_drop_if_referenced(
    entry: Mapping[str, Any],
    path: str,
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    affected = _affected_column(request)
    referenced: list[str] = []

    key = entry.get("key")
    if isinstance(key, str):
        if key == affected:
            referenced.append(f"{path}.key")
    elif _is_sequence(key):
        if affected in key:
            referenced.append(f"{path}.key")
    elif key is not None:
        failures.append(_malformed(f"{path}.key", f"_meta.{path}.key must be a string or list", request))

    for field in ("allowed_helpers", "default_helpers"):
        value = entry.get(field)
        if value is None:
            continue
        if not _is_sequence(value):
            failures.append(_malformed(f"{path}.{field}", f"_meta.{path}.{field} must be a list", request))
        elif affected in value:
            referenced.append(f"{path}.{field}")

    order = entry.get("order")
    if isinstance(order, Mapping):
        sort_by = order.get("sort_by")
        if isinstance(sort_by, str):
            if sort_by == affected:
                referenced.append(f"{path}.order.sort_by")
        elif _is_sequence(sort_by):
            if affected in sort_by:
                referenced.append(f"{path}.order.sort_by")
        elif sort_by is not None:
            failures.append(
                _malformed(
                    f"{path}.order.sort_by",
                    f"_meta.{path}.order.sort_by must be a string or list",
                    request,
                )
            )
    elif order is not None:
        failures.append(_malformed(f"{path}.order", f"_meta.{path}.order must be a mapping", request))

    # Lookup lists carry cross-field invariants (default_helpers within
    # allowed_helpers, sort_by within key/allowed_helpers), so pruning one
    # member is not a safe local edit; referenced drops always block,
    # mirroring the FK relation policy.
    for reference_path in referenced:
        changes.append(
            _change(
                ReferenceRoot.HELPER_POLICIES_LOOKUP,
                reference_path,
                ReferenceAction.BLOCKED,
                request.target_frame,
                affected,
                "Lookup policy pruning is blocked in this slice",
            )
        )
        failures.append(
            _blocked_reference(ReferenceRoot.HELPER_POLICIES_LOOKUP, reference_path, request, affected)
        )


def _lookup_updated(
    path: str,
    request: SchemaMaintenanceRequest,
    affected: str | None,
) -> MetadataReferenceChange:
    return _change(
        ReferenceRoot.HELPER_POLICIES_LOOKUP,
        path,
        ReferenceAction.UPDATED,
        request.target_frame,
        affected,
        f"Renamed lookup policy column to {request.target_column!r}",
    )


def _handle_fk_relations(
    relations: Sequence[Any],
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> list[Any]:
    updated_relations: list[Any] = []
    affected = _affected_column(request)
    for index, relation in enumerate(relations):
        path = f"helper_policies.fk.relations[{index}]"
        if not isinstance(relation, Mapping):
            failures.append(_malformed(path, f"_meta.{path} must be a mapping", request))
            updated_relations.append(relation)
            continue
        updated_relation = dict(relation)
        if request.kind == SchemaOperationKind.DROP_COLUMN:
            _block_fk_drop_if_referenced(relation, path, request, changes, failures)
            updated_relations.append(updated_relation)
            continue

        if request.kind != SchemaOperationKind.RENAME_COLUMN:
            updated_relations.append(updated_relation)
            continue

        if relation.get("source_frame") == request.target_frame and relation.get("source_column") == affected:
            updated_relation["source_column"] = request.target_column
            changes.append(
                _change(
                    ReferenceRoot.HELPER_POLICIES_FK,
                    f"{path}.source_column",
                    ReferenceAction.UPDATED,
                    request.target_frame,
                    affected,
                    f"Renamed FK relation source_column to {request.target_column!r}",
                )
            )
        if relation.get("target_frame") == request.target_frame and relation.get("target_key") == affected:
            updated_relation["target_key"] = request.target_column
            changes.append(
                _change(
                    ReferenceRoot.HELPER_POLICIES_FK,
                    f"{path}.target_key",
                    ReferenceAction.UPDATED,
                    request.target_frame,
                    affected,
                    f"Renamed FK relation target_key to {request.target_column!r}",
                )
            )
        helper_columns = relation.get("helper_columns")
        if relation.get("target_frame") == request.target_frame and _is_sequence(helper_columns):
            updated_relation["helper_columns"] = _rename_fk_helper_target_fields(
                helper_columns,
                path,
                request,
                changes,
            )
        updated_relations.append(updated_relation)
    return updated_relations


def _rename_fk_helper_target_fields(
    helper_columns: Sequence[Any],
    relation_path: str,
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
) -> list[Any]:
    updated_helpers: list[Any] = []
    affected = _affected_column(request)
    for index, helper in enumerate(helper_columns):
        if not isinstance(helper, Mapping):
            updated_helpers.append(helper)
            continue
        updated_helper = dict(helper)
        if helper.get("target_field") == affected:
            updated_helper["target_field"] = request.target_column
            changes.append(
                _change(
                    ReferenceRoot.HELPER_POLICIES_FK,
                    f"{relation_path}.helper_columns[{index}].target_field",
                    ReferenceAction.UPDATED,
                    request.target_frame,
                    affected,
                    f"Renamed FK helper target_field to {request.target_column!r}",
                )
            )
        updated_helpers.append(updated_helper)
    return updated_helpers


def _block_fk_drop_if_referenced(
    relation: Mapping[str, Any],
    path: str,
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    affected = _affected_column(request)
    referenced = False
    if relation.get("source_frame") == request.target_frame and relation.get("source_column") == affected:
        referenced = True
    if relation.get("target_frame") == request.target_frame and relation.get("target_key") == affected:
        referenced = True
    helper_columns = relation.get("helper_columns")
    if relation.get("target_frame") == request.target_frame and _is_sequence(helper_columns):
        referenced = referenced or any(
            isinstance(helper, Mapping) and helper.get("target_field") == affected
            for helper in helper_columns
        )
    if not referenced:
        return
    changes.append(
        _change(
            ReferenceRoot.HELPER_POLICIES_FK,
            path,
            ReferenceAction.BLOCKED,
            request.target_frame,
            affected,
            "FK relation pruning is blocked in this slice",
        )
    )
    failures.append(_blocked_reference(ReferenceRoot.HELPER_POLICIES_FK, path, request, affected))


def _handle_xref_crosstable(
    meta: dict[str, Any],
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    """Block schema changes that touch *real* XRef intent references.

    The XRef intent contract references columns in these places:

    * ``row_keys`` — shared row-identity vocabulary of the ``relation`` and
      ``matrix`` frames (one intent list serves both sides, so a one-sided
      rename cannot be rewritten safely);
    * ``column_keys`` — run-local matrix value-column labels (present only
      in-run or in hand-authored meta);
    * ``dense_axes.rows_from`` / ``columns_from`` ``key``/``keys`` on the
      configured axis frame;
    * ``dense_axes.resolved.column_keys`` — matrix value-column labels from
      a stored axis snapshot; ``_resolve_dense_axes`` consumes a
      resolved-only hand-authored configuration as a fallback, so these are
      real references on the ``matrix`` frame.

    Anything else inside the root — including legacy descriptive fields —
    is not a reference and is ignored. The generic key-name convention scan
    does not run on this root.
    """
    configs = meta.get("xref_crosstable")
    if configs is None:
        return
    if not isinstance(configs, Mapping):
        failures.append(
            _malformed("xref_crosstable", "_meta.xref_crosstable must be a mapping", request)
        )
        return
    affected = _affected_column(request)
    if affected is None:
        return

    for config_id, entry in configs.items():
        if not isinstance(entry, Mapping):
            continue
        path = f"xref_crosstable.{config_id}"
        if _xref_entry_references(entry, request.target_frame, affected):
            changes.append(
                _change(
                    ReferenceRoot.XREF_CROSSTABLE,
                    path,
                    ReferenceAction.BLOCKED,
                    request.target_frame,
                    affected,
                    "XRef intent references the affected column and is not rewritten",
                )
            )
            failures.append(
                _blocked_reference(ReferenceRoot.XREF_CROSSTABLE, path, request, affected)
            )


def _xref_entry_references(entry: Mapping[str, Any], frame: str, column: str) -> bool:
    def _in_list(value: Any) -> bool:
        return _is_sequence(value) and any(item == column for item in value)

    if entry.get("matrix") == frame or entry.get("relation") == frame:
        if _in_list(entry.get("row_keys")):
            return True

    dense = entry.get("dense_axes")
    if entry.get("matrix") == frame:
        if _in_list(entry.get("column_keys")):
            return True
        if isinstance(dense, Mapping):
            resolved = dense.get("resolved")
            if isinstance(resolved, Mapping) and _in_list(resolved.get("column_keys")):
                return True

    if isinstance(dense, Mapping):
        for axis_key in ("rows_from", "columns_from"):
            axis = dense.get(axis_key)
            if not isinstance(axis, Mapping) or axis.get("frame") != frame:
                continue
            if axis.get("key") == column or _in_list(axis.get("keys")):
                return True
    return False


def _handle_workbook_view(meta: dict[str, Any], failures: list[SchemaMaintenanceFailure]) -> None:
    value = meta.get("workbook_view")
    if value is None:
        return
    if not isinstance(value, Mapping):
        failures.append(
            SchemaMaintenanceFailure(
                code="malformed_meta",
                message="_meta.workbook_view must be a mapping",
                meta_path="workbook_view",
            )
        )
        return
    mappings = value.get("sheet_mappings")
    if mappings is not None and not _is_sequence(mappings):
        failures.append(
            SchemaMaintenanceFailure(
                code="malformed_meta",
                message="_meta.workbook_view.sheet_mappings must be a list",
                meta_path="workbook_view.sheet_mappings",
            )
        )
    sheets = value.get("sheets")
    if sheets is not None and not _is_sequence(sheets):
        failures.append(
            SchemaMaintenanceFailure(
                code="malformed_meta",
                message="_meta.workbook_view.sheets must be a list",
                meta_path="workbook_view.sheets",
            )
        )


def _handle_blocked_roots(
    meta: Mapping[str, Any],
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    affected = _affected_column(request)
    if affected is None:
        return
    for root_name in (
        "cell_codecs",
        "compact_multiaxis",
        "legend_blocks",
        "sparse_defaults",
        "split_by_discriminator",
    ):
        value = meta.get(root_name)
        if value is None:
            continue
        if contains_structured_reference(value, request.target_frame, affected):
            root = reference_root_for_blocked_name(root_name)
            changes.append(
                _change(
                    root,
                    root_name,
                    ReferenceAction.BLOCKED,
                    request.target_frame,
                    affected,
                    f"_meta.{root_name} references the affected column and is not rewritten",
                )
            )
            failures.append(_blocked_reference(root, root_name, request, affected))


def _handle_plugin_roots(
    meta: Mapping[str, Any],
    request: SchemaMaintenanceRequest,
    changes: list[MetadataReferenceChange],
    failures: list[SchemaMaintenanceFailure],
) -> None:
    affected = _affected_column(request)
    if affected is None:
        return
    for root_name, value in meta.items():
        if is_known_schema_maintenance_root(root_name) or is_out_of_scope_root(root_name):
            continue
        if root_name == "derived":
            continue
        if contains_structured_reference(value, request.target_frame, affected):
            changes.append(
                _change(
                    ReferenceRoot.UNKNOWN_PLUGIN,
                    root_name,
                    ReferenceAction.BLOCKED,
                    request.target_frame,
                    affected,
                    "Plugin-owned structured frame/column reference is not rewritten",
                )
            )
            failures.append(_blocked_reference(ReferenceRoot.UNKNOWN_PLUGIN, root_name, request, affected))


def _affected_column(request: SchemaMaintenanceRequest) -> str | None:
    if request.kind == SchemaOperationKind.ADD_COLUMN:
        return request.target_column
    return request.source_column


def _with_meta_if_changed(frames: Frames, updated_meta: dict[str, Any], changed: bool) -> Frames:
    if not changed:
        return frames
    out = dict(frames)
    out["_meta"] = updated_meta
    return out


def _result(
    frames: Frames,
    request: SchemaMaintenanceRequest,
    frame_changes: tuple[FrameChange, ...],
    metadata_changes: tuple[MetadataReferenceChange, ...],
    failures: tuple[SchemaMaintenanceFailure, ...],
) -> SchemaMaintenanceResult:
    report = SchemaMaintenanceReport(
        operation=request,
        frame_changes=frame_changes,
        metadata_changes=metadata_changes,
        failures=failures,
    )
    return SchemaMaintenanceResult(frames=frames, report=report)


def _blocked(
    original_frames: Frames,
    request: SchemaMaintenanceRequest,
    frame_changes: tuple[FrameChange, ...],
    metadata_changes: tuple[MetadataReferenceChange, ...],
    failures: tuple[SchemaMaintenanceFailure, ...],
) -> SchemaMaintenanceResult:
    return _result(dict(original_frames), request, frame_changes, metadata_changes, failures)


def _change(
    root: ReferenceRoot,
    path: str,
    action: ReferenceAction,
    frame: str | None,
    column: str | None,
    detail: str,
) -> MetadataReferenceChange:
    return MetadataReferenceChange(
        root=root,
        path=path,
        action=action,
        frame=frame,
        column=column,
        detail=detail,
    )


def _malformed(path: str, message: str, request: SchemaMaintenanceRequest) -> SchemaMaintenanceFailure:
    return _failure("malformed_meta", message, request.target_frame, _affected_column(request), path)


def _ambiguous(path: str, request: SchemaMaintenanceRequest, column: Any) -> SchemaMaintenanceFailure:
    return _failure(
        "ambiguous_metadata_reference",
        f"_meta.{path} cannot be resolved to a single frame",
        request.target_frame,
        str(column),
        path,
    )


def _blocked_reference(
    root: ReferenceRoot,
    path: str,
    request: SchemaMaintenanceRequest,
    column: str | None,
) -> SchemaMaintenanceFailure:
    return _failure(
        "blocking_metadata_reference",
        f"_meta.{path} references affected column {column!r} under {root.value}",
        request.target_frame,
        column,
        path,
    )


def _failure(
    code: str,
    message: str,
    frame: str | None,
    column: str | None,
    meta_path: str | None = None,
) -> SchemaMaintenanceFailure:
    return SchemaMaintenanceFailure(
        code=code,
        message=message,
        frame=frame,
        column=column,
        meta_path=meta_path,
    )


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))
