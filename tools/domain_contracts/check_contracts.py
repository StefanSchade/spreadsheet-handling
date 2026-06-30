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
    "concepts": (
        "id",
        "term",
        "status",
        "definition",
        "owning_capability_family",
        "reuse_check",
        "non_goals",
        "notes",
    ),
    "transformations": (
        "id",
        "runtime_name",
        "category",
        "callable",
        "pipeline_exposed",
        "status",
        "summary",
        "notes",
    ),
    "rules": ("id", "status", "rule", "consequence_if_violated", "notes"),
    "transformation_requirements": (
        "id",
        "transformation_id",
        "requirement_id",
        "relation",
        "notes",
    ),
    "concept_requirements": ("id", "concept_id", "requirement_id", "relation", "notes"),
    "rule_requirements": ("id", "rule_id", "requirement_id", "relation", "notes"),
    "transformation_frame_io": (
        "id",
        "transformation_id",
        "direction",
        "frame_pattern",
        "role",
        "required",
        "effect",
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
    "transformation_config_sources": (
        "id",
        "transformation_id",
        "source_kind",
        "source_path",
        "precedence",
        "required",
        "notes",
    ),
    "transformation_links": (
        "id",
        "source_transformation_id",
        "target_transformation_id",
        "relation",
        "notes",
    ),
}

BOOLEAN_FIELDS: dict[str, tuple[str, ...]] = {
    "transformations": ("pipeline_exposed",),
    "transformation_frame_io": ("required",),
    "transformation_meta_io": ("required",),
    "transformation_config_sources": ("required",),
}

TRANSFORMATION_CATEGORIES = frozenset(
    {
        "projection",
        "inverse_projection",
        "extraction",
        "validation",
        "workflow_infra",
        "wrapper",
        "configuration",
        "maintenance",
    }
)
FRAME_DIRECTIONS = frozenset({"read", "write", "read_write"})
META_DIRECTIONS = FRAME_DIRECTIONS
CONFIG_PRECEDENCE = frozenset(
    {
        "yaml_over_meta",
        "meta_over_yaml",
        "fill_if_absent",
        "error_on_conflict",
        "explicit_merge",
        "single_source",
    }
)
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

XREFS: dict[str, tuple[tuple[str, str], ...]] = {
    "transformation_requirements": (
        ("transformation_id", "transformations"),
        ("requirement_id", "requirements"),
    ),
    "concept_requirements": (("concept_id", "concepts"), ("requirement_id", "requirements")),
    "rule_requirements": (("rule_id", "rules"), ("requirement_id", "requirements")),
    "transformation_frame_io": (("transformation_id", "transformations"),),
    "transformation_meta_io": (("transformation_id", "transformations"),),
    "transformation_config_sources": (("transformation_id", "transformations"),),
    "transformation_links": (
        ("source_transformation_id", "transformations"),
        ("target_transformation_id", "transformations"),
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


def _validate_controlled_values(
    tables: dict[str, list[dict[str, Any]]], errors: list[dict[str, Any]]
) -> None:
    for index, row in enumerate(tables["transformations"]):
        if row.get("category") not in TRANSFORMATION_CATEGORIES:
            _error(
                errors,
                "transformations",
                "invalid_category",
                "Transformation category is not controlled",
                row_index=index,
                id=row.get("id", ""),
                value=row.get("category"),
            )
    for table in ("transformation_frame_io", "transformation_meta_io"):
        allowed = FRAME_DIRECTIONS if table == "transformation_frame_io" else META_DIRECTIONS
        for index, row in enumerate(tables[table]):
            if row.get("direction") not in allowed:
                _error(
                    errors,
                    table,
                    "invalid_direction",
                    "Direction is not controlled",
                    row_index=index,
                    id=row.get("id", ""),
                    value=row.get("direction"),
                )
    for index, row in enumerate(tables["transformation_config_sources"]):
        if row.get("precedence") not in CONFIG_PRECEDENCE:
            _error(
                errors,
                "transformation_config_sources",
                "invalid_precedence",
                "Config precedence is not controlled",
                row_index=index,
                id=row.get("id", ""),
                value=row.get("precedence"),
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


def _validate_xrefs(tables: dict[str, list[dict[str, Any]]], errors: list[dict[str, Any]]) -> None:
    ids = {
        table: {row.get("id") for row in rows if isinstance(row.get("id"), str)}
        for table, rows in tables.items()
    }
    for table, refs in XREFS.items():
        for index, row in enumerate(tables[table]):
            for field, target_table in refs:
                value = row.get(field)
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

