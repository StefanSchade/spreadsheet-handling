from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_DIR = ROOT / "registries" / "domain_contracts" / "canonical"
DEFAULT_REPORT_PATH = ROOT / "build" / "domain_contracts" / "domain_contract_health.json"

# Required fields per table. Rows must carry exactly these fields (see
# _validate_table_shape): a canonical schema change therefore fails the
# checker until this module is updated in the same change.
TABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "requirements": (
        "id",
        "status",
        "capability_family",
        "statement",
        "user_visible_effect",
        "source_kind",
        "source_ref",
        "notes",
    ),
    "transformations": (
        "id",
        "name",
        "trans_type",
        "trans_family",
        "operation_locus",
        "pipeline_exposed",
        "details",
        "inverse_transformation_id",
        "frames_in",
        "frames_out",
        "frames_consumed",
        "meta_in_buckets",
        "meta_workflow_prerequisites",
        "meta_or_config_input",
        "meta_out_buckets",
        "meta_output_content",
        "meta_output_consumer",
        "meta_output_loss_risks",
        "source_refs",
        "source_kind",
        "source_status",
        "human_reviewed",
        "notes",
    ),
    "transformation_types": ("id", "name", "detail", "bidirectional"),
    "transformation_families": ("id", "name", "details"),
    "meta_buckets": ("id", "name", "details", "lifecycle", "carrier_scope", "persisted"),
    "lifecycle_phase": ("id", "sequence", "name", "details"),
    "transformation_requirements": (
        "id",
        "transformation_id",
        "requirement_id",
        "relation",
        "notes",
    ),
    "transformation_meta_io": (
        "id",
        "transformation_id",
        "direction",
        "meta_path",
        "role",
        "required",
        "effect",
        "persistence_expectation",
        "notes",
    ),
    "transformation_links": (
        "id",
        "source_transformation_id",
        "target_transformation_id",
        "relation",
        "notes",
    ),
    "transformation_lifecycle_notes": (
        "id",
        "transformation_id",
        "lifecycle_phase_id",
        "role",
        "details",
        "source_refs",
        "status",
    ),
    "implementation_units": (
        "id",
        "name",
        "kind",
        "registered_step_id",
        "code_refs",
        "observed",
        "snapshot_date",
        "notes",
    ),
    "transformation_implementation_links": (
        "id",
        "transformation_id",
        "implementation_id",
        "relation",
        "notes",
    ),
    "transformation_features": (
        "id",
        "transformation_id",
        "name",
        "feature_kind",
        "details",
        "source_status",
        "evidence",
        "notes",
    ),
    "meta_reference_surfaces": (
        "id",
        "meta_root",
        "path_pattern",
        "target_kind",
        "maintenance_role",
        "rename_column_policy",
        "drop_column_policy",
        "owner",
        "evidence",
        "source_status",
        "notes",
    ),
    "implementation_gap_findings": (
        "id",
        "subject_kind",
        "subject_id",
        "finding",
        "disposition",
        "source_refs",
        "notes",
    ),
    "glossary": ("term", "area", "explanation", "related to"),
    "principles": ("statements",),
}

# Identity field per table; None disables the identity/uniqueness checks.
TABLE_ID_FIELDS: dict[str, str | None] = {
    table: "id" for table in TABLE_FIELDS
}
TABLE_ID_FIELDS["glossary"] = "term"
TABLE_ID_FIELDS["principles"] = None

# Fields that must be strict booleans when present.
STRICT_BOOLEAN_FIELDS: dict[str, tuple[str, ...]] = {
    "transformations": ("pipeline_exposed",),
    "transformation_meta_io": ("required",),
}

# Fields that must be a boolean or the empty string (unset).
OPTIONAL_BOOLEAN_FIELDS: dict[str, tuple[str, ...]] = {
    "transformations": ("human_reviewed",),
}

# All boolean-carrying fields; the ODS reimport normalizer coerces these
# back from spreadsheet carrier strings (see tools/domain_contracts/workbook.py).
BOOLEAN_FIELDS: dict[str, tuple[str, ...]] = {
    table: tuple(
        dict.fromkeys(
            STRICT_BOOLEAN_FIELDS.get(table, ()) + OPTIONAL_BOOLEAN_FIELDS.get(table, ())
        )
    )
    for table in set(STRICT_BOOLEAN_FIELDS) | set(OPTIONAL_BOOLEAN_FIELDS)
}

DIRECTIONS = frozenset({"read", "write", "read_write"})
LINK_RELATIONS = frozenset(
    {
        "inverse",
        "cleanup_inverse",
        "wraps",
        "wrapped_by",
        "consumes_output_of",
        "prepares_config_for",
    }
)
LIFECYCLE_NOTE_ROLES = frozenset(
    {"primary", "supporting", "risk", "open_question", "not_applicable"}
)
LIFECYCLE_NOTE_STATUSES = frozenset(
    {"draft_inferred", "reviewed", "approved", "deprecated"}
)
IMPLEMENTATION_UNIT_KINDS = frozenset(
    {"registered_step", "config_meta", "domain_function"}
)
IMPLEMENTATION_LINK_RELATIONS = frozenset(
    {"implements", "partially_implements", "alternative_implementation", "supporting"}
)
FEATURE_KINDS = frozenset({"suboperation"})
SURFACE_TARGET_KINDS = frozenset({"frame", "column", "column_list", "unknown"})
SURFACE_MAINTENANCE_ROLES = frozenset({"supported", "blocked", "ignored", "reported", "unknown"})
SURFACE_RENAME_POLICIES = frozenset({"update", "ignore", "block", "report", "unknown"})
SURFACE_DROP_POLICIES = frozenset(
    {"block", "block_unless_prune", "ignore", "report", "unknown"}
)
GAP_SUBJECT_KINDS = frozenset(
    {"transformation", "implementation_unit", "meta_reference_surface", "process"}
)
GAP_DISPOSITIONS = frozenset({"open", "accepted", "resolved"})

# Which table a gap finding's subject_id must resolve against, per subject_kind.
# "process" findings have no id table; their subject_id is free text.
GAP_SUBJECT_TABLES = {
    "transformation": "transformations",
    "implementation_unit": "implementation_units",
    "meta_reference_surface": "meta_reference_surfaces",
}

# Controlled single-value vocabularies: (table, field) -> (allowed values, error code).
CONTROLLED_VALUES: dict[tuple[str, str], tuple[frozenset[str], str]] = {
    ("transformation_meta_io", "direction"): (DIRECTIONS, "invalid_direction"),
    ("transformation_links", "relation"): (LINK_RELATIONS, "invalid_relation"),
    ("transformation_lifecycle_notes", "role"): (LIFECYCLE_NOTE_ROLES, "invalid_role"),
    ("transformation_lifecycle_notes", "status"): (LIFECYCLE_NOTE_STATUSES, "invalid_status"),
    ("implementation_units", "kind"): (IMPLEMENTATION_UNIT_KINDS, "invalid_kind"),
    ("transformation_implementation_links", "relation"): (
        IMPLEMENTATION_LINK_RELATIONS,
        "invalid_relation",
    ),
    ("transformation_features", "feature_kind"): (FEATURE_KINDS, "invalid_feature_kind"),
    ("meta_reference_surfaces", "target_kind"): (SURFACE_TARGET_KINDS, "invalid_target_kind"),
    ("meta_reference_surfaces", "maintenance_role"): (
        SURFACE_MAINTENANCE_ROLES,
        "invalid_maintenance_role",
    ),
    ("meta_reference_surfaces", "rename_column_policy"): (
        SURFACE_RENAME_POLICIES,
        "invalid_rename_policy",
    ),
    ("meta_reference_surfaces", "drop_column_policy"): (
        SURFACE_DROP_POLICIES,
        "invalid_drop_policy",
    ),
    ("implementation_gap_findings", "subject_kind"): (GAP_SUBJECT_KINDS, "invalid_subject_kind"),
    ("implementation_gap_findings", "disposition"): (GAP_DISPOSITIONS, "invalid_disposition"),
}

XREFS: dict[str, tuple[tuple[str, str], ...]] = {
    "transformations": (
        ("trans_type", "transformation_types"),
        ("trans_family", "transformation_families"),
        ("inverse_transformation_id", "transformations"),
    ),
    "transformation_requirements": (
        ("transformation_id", "transformations"),
        ("requirement_id", "requirements"),
    ),
    "transformation_meta_io": (("transformation_id", "transformations"),),
    "transformation_links": (
        ("source_transformation_id", "transformations"),
        ("target_transformation_id", "transformations"),
    ),
    "transformation_lifecycle_notes": (
        ("transformation_id", "transformations"),
        ("lifecycle_phase_id", "lifecycle_phase"),
    ),
    "transformation_implementation_links": (
        ("transformation_id", "transformations"),
        ("implementation_id", "implementation_units"),
    ),
    "transformation_features": (("transformation_id", "transformations"),),
}

# Comma-separated reference lists: every non-empty token must resolve.
MULTI_VALUE_XREFS: dict[str, tuple[tuple[str, str], ...]] = {
    "transformations": (
        ("meta_in_buckets", "meta_buckets"),
        ("meta_out_buckets", "meta_buckets"),
    ),
}


def _error(errors: list[dict[str, Any]], table: str, code: str, message: str, **extra: Any) -> None:
    errors.append({"table": table, "code": code, "message": message, **extra})


def _load_table(path: Path, table: str, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not path.exists():
        _error(errors, table, "missing_file", f"Missing required table file: {path}")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _error(errors, table, "invalid_json", str(exc), path=str(path))
        return []
    if not isinstance(data, list):
        _error(errors, table, "not_array", f"{path.name} must contain a JSON array")
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            _error(
                errors,
                table,
                "row_not_object",
                f"Row {index} must be a JSON object",
                row_index=index,
            )
            continue
        rows.append(item)
    return rows


def _row_id(table: str, row: dict[str, Any]) -> str:
    id_field = TABLE_ID_FIELDS[table]
    if id_field is None:
        return ""
    value = row.get(id_field)
    return value if isinstance(value, str) else ""


def _validate_table_shape(
    table: str, rows: list[dict[str, Any]], errors: list[dict[str, Any]]
) -> None:
    required = TABLE_FIELDS[table]
    allowed = set(required)
    id_field = TABLE_ID_FIELDS[table]
    seen_ids: dict[str, int] = {}
    for index, row in enumerate(rows):
        for field in required:
            if field not in row:
                _error(
                    errors,
                    table,
                    "missing_field",
                    f"Row {index} is missing required field {field!r}",
                    row_index=index,
                    field=field,
                )
        for field in row:
            if field not in allowed:
                _error(
                    errors,
                    table,
                    "unexpected_field",
                    f"Row {index} has unexpected field {field!r}; "
                    "schema changes must update tools/domain_contracts/check_contracts.py",
                    row_index=index,
                    field=field,
                )
        if id_field is not None:
            row_id = row.get(id_field)
            if not isinstance(row_id, str) or not row_id:
                _error(
                    errors,
                    table,
                    "invalid_id",
                    f"Row {index} has a missing or non-string {id_field}",
                    row_index=index,
                )
            elif row_id in seen_ids:
                _error(
                    errors,
                    table,
                    "duplicate_id",
                    f"Duplicate {id_field} {row_id!r}",
                    row_index=index,
                    first_row_index=seen_ids[row_id],
                    id=row_id,
                )
            else:
                seen_ids[row_id] = index

        for field in STRICT_BOOLEAN_FIELDS.get(table, ()):
            if field in row and not isinstance(row[field], bool):
                _error(
                    errors,
                    table,
                    "invalid_boolean",
                    f"Field {field!r} must be boolean",
                    row_index=index,
                    field=field,
                    id=_row_id(table, row),
                )
        for field in OPTIONAL_BOOLEAN_FIELDS.get(table, ()):
            if field in row and not isinstance(row[field], bool) and row[field] != "":
                _error(
                    errors,
                    table,
                    "invalid_boolean",
                    f"Field {field!r} must be boolean or empty",
                    row_index=index,
                    field=field,
                    id=_row_id(table, row),
                )


def _ids_by_table(tables: dict[str, list[dict[str, Any]]]) -> dict[str, set[str]]:
    return {
        table: {
            _row_id(table, row)
            for row in rows
            if _row_id(table, row)
        }
        for table, rows in tables.items()
    }


def _validate_xrefs(tables: dict[str, list[dict[str, Any]]], errors: list[dict[str, Any]]) -> None:
    ids = _ids_by_table(tables)
    for table, refs in XREFS.items():
        for index, row in enumerate(tables[table]):
            for field, target_table in refs:
                value = row.get(field)
                if value == "" or value is None:
                    continue
                if value not in ids[target_table]:
                    _error(
                        errors,
                        table,
                        "missing_reference",
                        f"{field!r} points to missing {target_table} id {value!r}",
                        row_index=index,
                        id=_row_id(table, row),
                        field=field,
                        value=value,
                        target_table=target_table,
                    )
    for table, refs in MULTI_VALUE_XREFS.items():
        for index, row in enumerate(tables[table]):
            for field, target_table in refs:
                raw = row.get(field)
                if not isinstance(raw, str) or not raw.strip():
                    continue
                for token in (part.strip() for part in raw.split(",")):
                    if token and token not in ids[target_table]:
                        _error(
                            errors,
                            table,
                            "missing_reference",
                            f"{field!r} contains missing {target_table} id {token!r}",
                            row_index=index,
                            id=_row_id(table, row),
                            field=field,
                            value=token,
                            target_table=target_table,
                        )


def _validate_gap_subjects(
    tables: dict[str, list[dict[str, Any]]], errors: list[dict[str, Any]]
) -> None:
    ids = _ids_by_table(tables)
    for index, row in enumerate(tables["implementation_gap_findings"]):
        target_table = GAP_SUBJECT_TABLES.get(row.get("subject_kind"))
        if target_table is None:
            continue  # process findings, or an invalid kind already reported
        subject_id = row.get("subject_id")
        if subject_id not in ids[target_table]:
            _error(
                errors,
                "implementation_gap_findings",
                "missing_reference",
                f"'subject_id' points to missing {target_table} id {subject_id!r}",
                row_index=index,
                id=_row_id("implementation_gap_findings", row),
                field="subject_id",
                value=subject_id,
                target_table=target_table,
            )


def _validate_controlled_values(
    tables: dict[str, list[dict[str, Any]]], errors: list[dict[str, Any]]
) -> None:
    for (table, field), (allowed, code) in CONTROLLED_VALUES.items():
        for index, row in enumerate(tables[table]):
            if row.get(field) not in allowed:
                _error(
                    errors,
                    table,
                    code,
                    f"Field {field!r} value is not controlled",
                    row_index=index,
                    id=_row_id(table, row),
                    field=field,
                    value=row.get(field),
                )


def _collect_warnings(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Non-fatal data-quality signals recorded in the report.

    These stay warnings because fixing them requires semantic registry
    cleanup (Review 005 FIN-REVIEW-005-P2-7 / P3-10), not tooling work.
    """
    warnings: list[dict[str, Any]] = []
    transformations = tables.get("transformations", [])
    by_id = {_row_id("transformations", row): row for row in transformations}

    names: dict[str, str] = {}
    for row in transformations:
        row_id = _row_id("transformations", row)
        name = row.get("name")
        if not isinstance(name, str) or not name:
            continue
        if name in names:
            warnings.append(
                {
                    "table": "transformations",
                    "code": "duplicate_name",
                    "message": f"Name {name!r} used by {names[name]!r} and {row_id!r}",
                    "id": row_id,
                }
            )
        else:
            names[name] = row_id

    for row in transformations:
        row_id = _row_id("transformations", row)
        inverse_id = row.get("inverse_transformation_id")
        if not inverse_id:
            continue
        inverse = by_id.get(inverse_id)
        if inverse is None:
            continue  # missing target already reported as an error
        if inverse.get("inverse_transformation_id") != row_id:
            warnings.append(
                {
                    "table": "transformations",
                    "code": "asymmetric_inverse",
                    "message": (
                        f"{row_id!r} names inverse {inverse_id!r}, but {inverse_id!r} "
                        f"names {inverse.get('inverse_transformation_id')!r}"
                    ),
                    "id": row_id,
                }
            )
    return warnings


def _phase_sequence(row: dict[str, Any]) -> int | None:
    try:
        return int(str(row.get("sequence", "")).strip())
    except ValueError:
        return None


def _validate_lifecycle_phase_sequences(
    tables: dict[str, list[dict[str, Any]]], errors: list[dict[str, Any]]
) -> None:
    seen: dict[int, str] = {}
    for index, row in enumerate(tables["lifecycle_phase"]):
        sequence = _phase_sequence(row)
        if sequence is None:
            _error(
                errors,
                "lifecycle_phase",
                "invalid_sequence",
                "Lifecycle phase sequence must sort numerically",
                row_index=index,
                id=row.get("id", ""),
                value=row.get("sequence"),
            )
            continue
        if sequence in seen:
            _error(
                errors,
                "lifecycle_phase",
                "duplicate_sequence",
                f"Duplicate lifecycle phase sequence {sequence}",
                row_index=index,
                id=row.get("id", ""),
                first_id=seen[sequence],
                value=row.get("sequence"),
            )
        else:
            seen[sequence] = str(row.get("id", ""))


def sorted_lifecycle_phases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (_phase_sequence(row) is None, _phase_sequence(row) or 0))


def load_contract_tables(registry_dir: Path | str = DEFAULT_REGISTRY_DIR) -> dict[str, list[dict[str, Any]]]:
    registry = Path(registry_dir)
    errors: list[dict[str, Any]] = []
    tables = {
        table: _load_table(registry / f"{table}.json", table, errors)
        for table in TABLE_FIELDS
    }
    if errors:
        raise ValueError(json.dumps(errors, indent=2))
    return tables


def check_contracts(
    registry_dir: Path | str = DEFAULT_REGISTRY_DIR,
    report_path: Path | str = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    registry = Path(registry_dir)
    errors: list[dict[str, Any]] = []
    tables = {
        table: _load_table(registry / f"{table}.json", table, errors)
        for table in TABLE_FIELDS
    }
    for table, rows in tables.items():
        _validate_table_shape(table, rows, errors)
    _validate_controlled_values(tables, errors)
    _validate_lifecycle_phase_sequences(tables, errors)
    _validate_xrefs(tables, errors)
    _validate_gap_subjects(tables, errors)
    warnings = _collect_warnings(tables)

    report = {
        "registry_dir": str(registry),
        "table_count": len(TABLE_FIELDS),
        "tables": {table: {"rows": len(rows)} for table, rows in tables.items()},
        "error_count": len(errors),
        "errors": errors,
        "warning_count": len(warnings),
        "warnings": warnings,
        "status": "error" if errors else "ok",
    }

    output = Path(report_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate domain-contract registry JSON.")
    parser.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRY_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args(argv)

    report = check_contracts(args.registry_dir, args.report)
    print(args.report)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
