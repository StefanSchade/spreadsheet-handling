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
    _handle_frame_lifecycle(updated_meta, request, failures)
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

    for key, value in fk.items():
        if key in {"relations", "schema_version"}:
            continue
        if contains_structured_reference(value, request.target_frame, _affected_column(request) or ""):
            path = f"helper_policies.fk.{key}"
            changes.append(
                _change(
                    ReferenceRoot.HELPER_POLICIES_FK,
                    path,
                    ReferenceAction.BLOCKED,
                    request.target_frame,
                    _affected_column(request),
                    "Residual v1 FK helper policy is not rewritten in this slice",
                )
            )
            failures.append(_blocked_reference(ReferenceRoot.HELPER_POLICIES_FK, path, request, _affected_column(request)))

    updated_helper_policies = dict(helper_policies)
    updated_helper_policies["fk"] = updated_fk
    meta["helper_policies"] = updated_helper_policies


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


def _handle_frame_lifecycle(
    meta: dict[str, Any],
    request: SchemaMaintenanceRequest,
    failures: list[SchemaMaintenanceFailure],
) -> None:
    value = meta.get("frame_lifecycle")
    if value is not None and not isinstance(value, Mapping):
        failures.append(_malformed("frame_lifecycle", "_meta.frame_lifecycle must be a mapping", request))


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
        "xref_crosstable",
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
