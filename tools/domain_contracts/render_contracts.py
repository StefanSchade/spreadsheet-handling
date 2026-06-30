from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.domain_contracts.check_contracts import (
    DEFAULT_REGISTRY_DIR,
    sorted_lifecycle_phases,
    load_contract_tables,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = ROOT / "docs_generated" / "domain_contracts" / "domain_contracts.adoc"
DEFAULT_REPORT_PATH = ROOT / "build" / "domain_contracts" / "domain_contract_health.json"


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", r"\|").replace("\n", " ").replace("\r", " ")


def _table(headers: tuple[str, ...], rows: list[dict[str, Any]]) -> list[str]:
    lines = ["[cols=\"" + ",".join(["1"] * len(headers)) + "\", options=\"header\"]", "|===", ""]
    lines.append("| " + " | ".join(headers))
    for row in rows:
        lines.append("| " + " | ".join(_cell(row.get(header, "")) for header in headers))
    lines.append("|===")
    return lines


def _by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id", "")): row for row in rows}


def _diagnostics(report_path: Path) -> dict[str, Any] | None:
    if not report_path.exists():
        return None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "unreadable", "error_count": "unknown"}
    if isinstance(report, dict):
        return report
    return {"status": "unreadable", "error_count": "unknown"}


def _transformation_label(row: dict[str, Any]) -> str:
    name = str(row.get("name", ""))
    return f"{row.get('id', '')} ({name})" if name else str(row.get("id", ""))


def _lifecycle_note_cell(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return ""
    parts = []
    for note in sorted(notes, key=lambda row: (row.get("role", ""), row.get("id", ""))):
        role = str(note.get("role", ""))
        details = str(note.get("details", ""))
        parts.append(f"{role}: {details}" if role else details)
    return " + ".join(parts)


def _notes_by_transform_phase(
    notes: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for note in notes:
        grouped[(str(note.get("transformation_id", "")), str(note.get("lifecycle_phase_id", "")))].append(
            note
        )
    return grouped


def render_lifecycle_matrix(
    tables: dict[str, list[dict[str, Any]]],
    output_path: Path | str,
) -> Path:
    output = Path(output_path)
    phases = sorted_lifecycle_phases(tables["lifecycle_phase"])
    transformations = sorted(tables["transformations"], key=lambda row: str(row.get("id", "")))
    grouped = _notes_by_transform_phase(tables["transformation_lifecycle_notes"])

    headers = ("Transformation", *[str(phase.get("name", phase.get("id", ""))) for phase in phases])
    lines: list[str] = [
        "= Transformation Lifecycle Matrix",
        ":toc:",
        "",
        "Generated draft extract from `registries/domain_contracts/canonical/transformation_lifecycle_notes.json`.",
        "Lifecycle note text is `draft_inferred` unless the source row says otherwise.",
        "",
        "[cols=\"" + ",".join(["2"] + ["3"] * len(phases)) + "\", options=\"header\"]",
        "|===",
        "",
        "| " + " | ".join(headers),
    ]

    for transform in transformations:
        row_values = [_transformation_label(transform)]
        for phase in phases:
            notes = grouped.get((str(transform.get("id", "")), str(phase.get("id", ""))), [])
            row_values.append(_lifecycle_note_cell(notes))
        lines.append("| " + " | ".join(_cell(value) for value in row_values))
    lines.append("|===")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    return output


def render_lifecycle_by_phase(
    tables: dict[str, list[dict[str, Any]]],
    output_path: Path | str,
) -> Path:
    output = Path(output_path)
    transforms = _by_id(tables["transformations"])
    notes_by_phase: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for note in tables["transformation_lifecycle_notes"]:
        notes_by_phase[str(note.get("lifecycle_phase_id", ""))].append(note)

    lines: list[str] = [
        "= Transformation Lifecycle By Phase",
        ":toc:",
        "",
        "Generated draft extract from `registries/domain_contracts/canonical/transformation_lifecycle_notes.json`.",
        "",
    ]

    for phase in sorted_lifecycle_phases(tables["lifecycle_phase"]):
        phase_id = str(phase.get("id", ""))
        lines.extend(
            [
                f"== {_cell(phase.get('name', phase_id))}",
                "",
                _cell(phase.get("details", "")),
                "",
            ]
        )
        rows = []
        for note in sorted(
            notes_by_phase.get(phase_id, []),
            key=lambda row: (row.get("transformation_id", ""), row.get("role", ""), row.get("id", "")),
        ):
            transform = transforms.get(str(note.get("transformation_id", "")), {})
            rows.append(
                {
                    "transformation": _transformation_label(transform) or note.get("transformation_id", ""),
                    "role": note.get("role", ""),
                    "status": note.get("status", ""),
                    "details": note.get("details", ""),
                    "source_refs": note.get("source_refs", ""),
                }
            )
        if rows:
            lines.extend(_table(("transformation", "role", "status", "details", "source_refs"), rows))
        else:
            lines.append("_No lifecycle notes._")
        lines.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    return output


def render_contracts(
    registry_dir: Path | str = DEFAULT_REGISTRY_DIR,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    report_path: Path | str = DEFAULT_REPORT_PATH,
) -> Path:
    tables = load_contract_tables(registry_dir)
    transformations = _by_id(tables["transformations"])
    output = Path(output_path)

    lines: list[str] = [
        "= Domain Contracts Extract",
        ":toc:",
        "",
        "Generated from `registries/domain_contracts/canonical`.",
        "",
        "== Requirements",
        "",
        *_table(
            ("id", "status", "capability_family", "statement", "user_visible_effect"),
            tables["requirements"],
        ),
        "",
        "== Transformation Types",
        "",
        *_table(("id", "name", "detail", "bidirectional"), tables["transformation_types"]),
        "",
        "== Transformation Families",
        "",
        *_table(("id", "name", "details"), tables["transformation_families"]),
        "",
        "== Transformations",
        "",
        *_table(
            ("id", "name", "trans_type", "trans_family", "pipeline_exposed", "details"),
            tables["transformations"],
        ),
        "",
        "== Lifecycle Phases",
        "",
        *_table(("id", "sequence", "name", "details"), sorted_lifecycle_phases(tables["lifecycle_phase"])),
        "",
        "== Transformation Meta IO",
        "",
        *_table(
            (
                "id",
                "transformation_id",
                "direction",
                "meta_path",
                "role",
                "required",
                "persistence_expectation",
            ),
            tables["transformation_meta_io"],
        ),
        "",
        "== Transformation Links",
        "",
        *_table(
            ("id", "source_transformation_id", "target_transformation_id", "relation", "notes"),
            tables["transformation_links"],
        ),
        "",
        "== Requirement Coverage Seed",
        "",
    ]

    for row in sorted(tables["transformation_requirements"], key=lambda item: item.get("id", "")):
        transform_id = str(row.get("transformation_id", ""))
        transform = transformations.get(transform_id, {})
        lines.append(
            f"* `{_cell(transform_id)}` ({_cell(transform.get('name', ''))}) "
            f"{_cell(row.get('relation', ''))} `{_cell(row.get('requirement_id', ''))}`"
        )

    diagnostics = _diagnostics(Path(report_path))
    lines.extend(["", "== Diagnostics", ""])
    if diagnostics is None:
        lines.append("No diagnostic report found yet.")
    else:
        lines.append(f"* Status: `{_cell(diagnostics.get('status', 'unknown'))}`")
        lines.append(f"* Errors: `{_cell(diagnostics.get('error_count', 'unknown'))}`")
        table_counts = diagnostics.get("tables", {})
        if isinstance(table_counts, dict):
            lines.append(f"* Tables checked: `{len(table_counts)}`")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    render_lifecycle_matrix(tables, output.parent / "transformation_lifecycle_matrix.adoc")
    render_lifecycle_by_phase(tables, output.parent / "transformation_lifecycle_by_phase.adoc")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render domain-contract ADOC extracts.")
    parser.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRY_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args(argv)

    output = render_contracts(args.registry_dir, args.output, args.report)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
