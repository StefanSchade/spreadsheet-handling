from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVED_DIR = ROOT / "project_memory" / "derived"
OUTPUT_PATH = ROOT / "docs_generated" / "project_memory" / "current_context.adoc"


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    rows: list[dict[str, str]] = []
    for item in data:
        if isinstance(item, dict):
            rows.append({str(k): "" if v is None else str(v) for k, v in item.items()})
    return rows


def _escape_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", r"\|").replace("\n", " ").replace("\r", " ")


def _table(lines: list[list[str]], columns: int) -> list[str]:
    out = ["[cols=\"" + ",".join(["1"] * columns) + "\",options=\"header\"]", "|==="]
    for row in lines:
        out.extend(row)
    out.append("|===")
    return out


def _section(title: str, rows: list[dict[str, str]], headers: list[str], keys: list[str], empty_note: str) -> list[str]:
    lines = [f"== {title}", ""]
    if not rows:
        lines.extend([empty_note, ""])
        return lines

    table_lines: list[list[str]] = []
    table_lines.append([f"|{h}" for h in headers])
    for row in rows:
        table_lines.append([f"|{_escape_cell(row.get(key, ''))}" for key in keys])
    lines.extend(_table(table_lines, len(headers)))
    lines.append("")
    return lines


def render_current_context(output_path: Path | str = OUTPUT_PATH) -> Path:
    output = Path(output_path)
    current_findings = _read_rows(DERIVED_DIR / "current_findings.json")
    blockers = _read_rows(DERIVED_DIR / "ftr_blockers.json")
    edges = _read_rows(DERIVED_DIR / "ftr_dependency_edges.json")

    lines: list[str] = [
        "= Current Project Memory Context",
        "",
        "Generated from `project_memory/canonical` via `make memory-query`.",
        "",
        "[NOTE]",
        "====",
        "This file is generated. Do not edit by hand.",
        "It is intended for LLM/review handoff, not as stable user documentation.",
        "====",
        "",
    ]

    lines.extend(
        _section(
            "Current Findings",
            current_findings,
            ["Severity", "Status", "Topic", "Current relevance", "Summary", "Target"],
            ["severity", "status", "topic", "current_relevance", "summary", "target_id"],
            "No current findings were derived from the current data set.",
        )
    )
    lines.extend(
        _section(
            "FTR Blockers",
            blockers,
            ["Source FTR", "Source title", "Relation", "Target FTR", "Target status", "Note"],
            ["source_ftr_id", "source_title", "relation", "target_ftr_id", "target_status", "note"],
            "No active blocker edges were derived from the current data set.",
        )
    )
    lines.extend(
        _section(
            "Active Dependency Edges",
            edges,
            ["Source FTR", "Relation", "Target FTR", "Status", "Note"],
            ["source_ftr_id", "relation", "target_ftr_id", "status", "note"],
            "No active dependency edges were derived from the current data set.",
        )
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return output


if __name__ == "__main__":
    render_current_context()
