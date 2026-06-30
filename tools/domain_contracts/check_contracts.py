from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_DIR = ROOT / "registries" / "domain_contracts" / "canonical"
DEFAULT_REPORT_PATH = ROOT / "build" / "domain_contracts" / "domain_contract_health.json"

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
        "pipeline_exposed",
        "details",
        "inverse_transformation_id",
        "configuration_input",
        "input_meta",
        "output_meta",
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
}

BOOLEAN_FIELDS: dict[str, tuple[str, ...]] = {
    "transformations": ("pipeline_exposed",),
    "transformation_meta_io": ("required",),
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


def _validate_table_shape(
    table: str, rows: list[dict[str, Any]], errors: list[dict[str, Any]]
) -> None:
    required = TABLE_FIELDS[table]
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
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            _error(
                errors,
                table,
                "invalid_id",
                f"Row {index} has a missing or non-string id",
                row_index=index,
            )
        elif row_id in seen_ids:
            _error(
                errors,
                table,
                "duplicate_id",
                f"Duplicate id {row_id!r}",
                row_index=index,
                first_row_index=seen_ids[row_id],
                id=row_id,
            )
        else:
            seen_ids[row_id] = index

        for field in BOOLEAN_FIELDS.get(table, ()):
            if field in row and not isinstance(row[field], bool):
                _error(
                    errors,
                    table,
                    "invalid_boolean",
                    f"Field {field!r} must be boolean",
                    row_index=index,
                    field=field,
                    id=row.get("id", ""),
                )


def _ids_by_table(tables: dict[str, list[dict[str, Any]]]) -> dict[str, set[str]]:
    return {
        table: {row.get("id") for row in rows if isinstance(row.get("id"), str)}
        for table, rows in tables.items()
    }


def _validate_xrefs(tables: dict[str, list[dict[str, Any]]], errors: list[dict[str, Any]]) -> None:
    ids = _ids_by_table(tables)
    for table, refs in XREFS.items():
        for index, row in enumerate(tables[table]):
            for field, target_table in refs:
                value = row.get(field)
                if value == "":
                    continue
                if value not in ids[target_table]:
                    _error(
                        errors,
                        table,
                        "missing_reference",
                        f"{field!r} points to missing {target_table} id {value!r}",
                        row_index=index,
                        id=row.get("id", ""),
                        field=field,
                        value=value,
                        target_table=target_table,
                    )


def _validate_controlled_values(
    tables: dict[str, list[dict[str, Any]]], errors: list[dict[str, Any]]
) -> None:
    for index, row in enumerate(tables["transformation_meta_io"]):
        if row.get("direction") not in DIRECTIONS:
            _error(
                errors,
                "transformation_meta_io",
                "invalid_direction",
                "Direction is not controlled",
                row_index=index,
                id=row.get("id", ""),
                value=row.get("direction"),
            )
    for index, row in enumerate(tables["transformation_links"]):
        if row.get("relation") not in LINK_RELATIONS:
            _error(
                errors,
                "transformation_links",
                "invalid_relation",
                "Transformation link relation is not controlled",
                row_index=index,
                id=row.get("id", ""),
                value=row.get("relation"),
            )
    for index, row in enumerate(tables["transformation_lifecycle_notes"]):
        if row.get("role") not in LIFECYCLE_NOTE_ROLES:
            _error(
                errors,
                "transformation_lifecycle_notes",
                "invalid_role",
                "Lifecycle note role is not controlled",
                row_index=index,
                id=row.get("id", ""),
                value=row.get("role"),
            )
        if row.get("status") not in LIFECYCLE_NOTE_STATUSES:
            _error(
                errors,
                "transformation_lifecycle_notes",
                "invalid_status",
                "Lifecycle note status is not controlled",
                row_index=index,
                id=row.get("id", ""),
                value=row.get("status"),
            )


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

    report = {
        "registry_dir": str(registry),
        "table_count": len(TABLE_FIELDS),
        "tables": {table: {"rows": len(rows)} for table, rows in tables.items()},
        "error_count": len(errors),
        "errors": errors,
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
