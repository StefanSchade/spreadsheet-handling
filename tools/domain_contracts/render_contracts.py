from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.domain_contracts.check_contracts import DEFAULT_REGISTRY_DIR, load_contract_tables

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


def render_contracts(
    registry_dir: Path | str = DEFAULT_REGISTRY_DIR,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    report_path: Path | str = DEFAULT_REPORT_PATH,
) -> Path:
    tables = load_contract_tables(registry_dir)
    transformations = _by_id(tables["transformations"])

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
        "== Concepts",
        "",
        *_table(("id", "term", "status", "definition", "owning_capability_family"), tables["concepts"]),
        "",
        "== Transformations",
        "",
        *_table(("id", "runtime_name", "category", "pipeline_exposed", "summary"), tables["transformations"]),
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
        "== Transformation Frame IO",
        "",
        *_table(
            ("id", "transformation_id", "direction", "frame_pattern", "role", "required", "effect"),
            tables["transformation_frame_io"],
        ),
        "",
        "== Transformation Links",
        "",
        *_table(
            ("id", "source_transformation_id", "target_transformation_id", "relation", "notes"),
            tables["transformation_links"],
        ),
        "",
        "== Rules",
        "",
        *_table(("id", "status", "rule", "consequence_if_violated"), tables["rules"]),
        "",
        "== Requirement Coverage Seed",
        "",
    ]

    for row in sorted(tables["transformation_requirements"], key=lambda item: item.get("id", "")):
        transform_id = str(row.get("transformation_id", ""))
        transform = transformations.get(transform_id, {})
        lines.append(
            f"* `{_cell(transform_id)}` ({_cell(transform.get('runtime_name', ''))}) "
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

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render domain-contract ADOC extract.")
    parser.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRY_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args(argv)

    output = render_contracts(args.registry_dir, args.output, args.report)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

