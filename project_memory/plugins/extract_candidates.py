from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FTR_SOURCE_GLOBS = [
    "docs/backlog/**/*.adoc",
    "docs/cold_storage/backlog/**/*.adoc",
]
REVIEW_SOURCE_GLOBS = [
    "docs/cold_storage/reviews/**/*.adoc",
    "docs/warm_storage/global_reviews/*.adoc",
]
OUTPUT_DIR = ROOT / "project_memory" / "extracted"

ID_RE = re.compile(r"\b(?:FTR|BUG|REV|FIN|DEC|REL)-[A-Z0-9][A-Z0-9_-]*\b")
LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _/-]{1,40}):\s*(.+?)\s*$")
LABEL_BOLD_RE = re.compile(r"^\s*\*([^*]+?)\s*:\*\s*(?::\s*)?(.+?)\s*$")
HEADING_RE = re.compile(r"^(=+)\s+(.+?)\s*$")
PRIORITY_RE = re.compile(r"\b(P[0-9A-Z]+)\b")
FTR_PRIORITY_RE = re.compile(r"-(P(?:1|2|3[A-Z]?|4[A-Z]?|5|6|7|8|9|10))$")
STATUS_CANON_RE = re.compile(r"\b(done|new|draft|open|superseded)\b", re.IGNORECASE)


def _source_files() -> list[Path]:
    files: list[Path] = []
    for pattern in FTR_SOURCE_GLOBS + REVIEW_SOURCE_GLOBS:
        files.extend(sorted(ROOT.glob(pattern)))
    return sorted({p for p in files if p.is_file()})


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return cleaned.lower()


def _strip_suffixes(stem: str) -> str:
    out = stem
    while True:
        new = re.sub(r"(?i)(?:_(?:review|implementation_review|package_review|analysis|assessment|decision|summary|final_review|final_summary|reassessment|prompt(?:_\d+)?|slice\d+|codex|claude_code))+$", "", out)
        if new == out:
            return out
        out = new


def _first_id(text: str) -> str:
    for match in ID_RE.finditer(text):
        start = match.start()
        end = match.end()
        prev = text[start - 1] if start > 0 else ""
        next_ = text[end] if end < len(text) else ""
        if start > 0 and prev.isalnum():
            continue
        if prev == "-" and start > 1 and text[start - 2].isalpha():
            continue
        if next_ and next_.isalnum():
            continue
        return match.group(0)
    return ""


def _candidate_id(prefix: str, source: Path, fallback: str) -> str:
    base_name = _strip_suffixes(source.stem)
    base = _first_id(base_name) or _first_id(source.name) or _first_id(fallback) or _slugify(base_name)
    return f"{prefix}-{base}" if base else f"{prefix}-{_slugify(source.stem)}"


def _parse_labels(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        m = LABEL_BOLD_RE.match(line) or LABEL_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip().lower().replace(" ", "_")
        value = m.group(2).strip()
        if key == "status":
            status = STATUS_CANON_RE.search(value)
            out[key] = status.group(1).lower() if status else value.lower()
        else:
            out[key] = value
    return out


def _find_heading(lines: list[str]) -> tuple[str, int]:
    for idx, line in enumerate(lines, start=1):
        m = HEADING_RE.match(line)
        if m:
            heading = m.group(2).strip()
            if heading:
                return heading, idx
    return "", 0


def _extract_status(text: str) -> str:
    lowered = text.lower()
    for status in ("draft", "active", "accepted", "resolved", "superseded", "wontfix", "open", "closed"):
        if re.search(rf"\b{re.escape(status)}\b", lowered):
            return status
    return ""


def _extract_priority(text: str) -> str:
    m = PRIORITY_RE.search(text.upper())
    return m.group(1) if m else ""


def _priority_from_stem(stem: str) -> str:
    m = FTR_PRIORITY_RE.search(stem.upper())
    return m.group(1) if m else ""


def _extract_section_paragraph(lines: list[str], section_names: set[str]) -> str:
    section_start = None
    for idx, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if not m:
            continue
        heading = m.group(2).strip().lower()
        if heading in section_names:
            section_start = idx + 1
            break
    if section_start is None:
        return ""

    collected: list[str] = []
    started = False
    for line in lines[section_start:]:
        if HEADING_RE.match(line):
            break
        stripped = line.strip()
        if not stripped:
            if started:
                break
            continue
        if stripped.startswith(("* ", "**", "*", "`", "+")) and started:
            break
        started = True
        collected.append(re.sub(r"`([^`]+)`", r"\1", stripped))
    return re.sub(r"\s+", " ", " ".join(collected)).strip()


def _review_scope_area(path: Path) -> tuple[str, str]:
    rel = path.relative_to(ROOT).as_posix()
    review_scope = "unknown"
    review_area = "unknown"
    if rel.startswith("docs/warm_storage/global_reviews/"):
        review_scope = "warm_global"
        review_area = "global"
        return review_scope, review_area
    if rel.startswith("docs/cold_storage/reviews/"):
        review_scope = "global" if "global_reviews" in rel else "topic"
        review_area = "global"
        if "topic_reviews" in rel:
            if "domain_reviews" in rel:
                review_area = "domain"
            elif "package_reviews" in rel:
                review_area = "package"
            elif "fk_helper_reviews" in rel:
                review_area = "fk_helper"
            elif "meta_reviews" in rel:
                review_area = "meta"
            else:
                review_area = "topic"
        return review_scope, review_area
    return review_scope, review_area


def _is_primary_ftr_file(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith("docs/backlog/") and path.name.startswith(("FTR-", "BUG-")) and path.suffix == ".adoc" and "_" not in path.stem:
        return True
    if rel.startswith("docs/cold_storage/backlog/ftrs_done/") and path.name.startswith(("FTR-", "BUG-")) and path.suffix == ".adoc" and "_" not in path.stem:
        return True
    return False


def _is_companion_ftr_file(path: Path) -> bool:
    return "_" in path.stem


def _extract_ftr_candidates(path: Path, lines: list[str]) -> list[dict[str, str]]:
    if not _is_primary_ftr_file(path) or _is_companion_ftr_file(path):
        return []
    heading, heading_line = _find_heading(lines)
    labels = _parse_labels(lines[:60])
    purpose = labels.get("purpose", "") or _extract_section_paragraph(lines, {"purpose", "zweck"})
    fid = path.stem
    candidate: dict[str, str] = {
        "id": fid,
        "title": heading or labels.get("title", ""),
        "status": labels.get("status", ""),
        "priority": labels.get("priority", "") or _priority_from_stem(path.stem),
        "purpose": purpose or labels.get("summary", ""),
        "source_path": str(path.relative_to(ROOT)),
        "line_start": str(heading_line or 1),
    }
    if fid or candidate["title"]:
        return [candidate]
    return []


def _extract_review_candidates(path: Path, lines: list[str]) -> list[dict[str, str]]:
    heading, heading_line = _find_heading(lines)
    content = "\n".join(lines[:40])
    rel = path.relative_to(ROOT).as_posix()
    if not (rel.startswith("docs/cold_storage/reviews/") or rel.startswith("docs/warm_storage/global_reviews/")):
        return []
    name = _strip_suffixes(path.stem).lower()
    stem = path.stem.lower()
    if any(token in stem for token in ("prompt", "shell", "summary", "notes", "index")):
        return []
    if "review" not in (name + " " + heading).lower() and "review" not in content.lower():
        return []
    rid = _first_id(_strip_suffixes(path.stem)) or _first_id(path.name) or _first_id(heading) or _candidate_id("REV", path, heading or "review")
    labels = _parse_labels(lines[:80])
    review_scope, review_area = _review_scope_area(path)
    return [{
        "id": rid,
        "title": heading or labels.get("title", "") or path.stem,
        "status": labels.get("status", "") or _extract_status(content),
        "purpose": labels.get("purpose", "") or labels.get("summary", ""),
        "review_scope": review_scope,
        "review_area": review_area,
        "source_path": str(path.relative_to(ROOT)),
        "line_start": str(heading_line or 1),
    }]


def _extract_finding_candidates(path: Path, lines: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    rel = path.relative_to(ROOT).as_posix()
    if not (rel.startswith("docs/cold_storage/reviews/") or rel.startswith("docs/warm_storage/global_reviews/")):
        return out
    review_scope, review_area = _review_scope_area(path)
    current_heading = ""
    current_line = 0
    for idx, line in enumerate(lines, start=1):
        m = HEADING_RE.match(line)
        if m:
            current_heading = m.group(2).strip()
            current_line = idx
            if not current_heading:
                continue
            lowered = current_heading.lower()
            if not any(
                token in lowered
                for token in ("findings", "finding", "open findings", "high findings", "medium findings", "low findings", "blockers", "risks", "residual risks")
            ):
                continue
            text = "\n".join(lines[max(0, idx - 3): min(len(lines), idx + 8)])
            labels = _parse_labels(lines[max(0, idx - 8): min(len(lines), idx + 20)])
            candidate = {
                "id": _first_id(_strip_suffixes(path.stem)) or _first_id(path.name) or _first_id(current_heading) or _candidate_id("FIN", path, current_heading),
                "title": current_heading,
                "severity": labels.get("severity", "") or ("blocker" if "blocker" in lowered else ""),
                "status": labels.get("status", "") or _extract_status(text),
                "summary": labels.get("summary", "") or "",
                "review_scope": review_scope,
                "review_area": review_area,
                "source_path": str(path.relative_to(ROOT)),
                "line_start": str(current_line),
            }
            out.append(candidate)
    return out


def _write_json(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def extract_candidates() -> dict[str, Path]:
    ftrs: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    findings: list[dict[str, str]] = []

    for path in _source_files():
        lines = _read_lines(path)
        ftrs.extend(_extract_ftr_candidates(path, lines))
        review_rows = _extract_review_candidates(path, lines)
        reviews.extend(review_rows)
        if review_rows:
            findings.extend(_extract_finding_candidates(path, lines))

    def _dedupe(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[tuple[str, str]] = set()
        out: list[dict[str, str]] = []
        for row in rows:
            key = (row.get("id", ""), row.get("source_path", ""))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    ftrs = _dedupe(sorted(ftrs, key=lambda r: (r.get("id", ""), r.get("source_path", ""))))
    reviews = _dedupe(sorted(reviews, key=lambda r: (r.get("id", ""), r.get("source_path", ""))))
    findings = _dedupe(sorted(findings, key=lambda r: (r.get("id", ""), r.get("source_path", ""))))

    outputs = {
        "ftr_candidates.json": OUTPUT_DIR / "ftr_candidates.json",
        "review_candidates.json": OUTPUT_DIR / "review_candidates.json",
        "finding_candidates.json": OUTPUT_DIR / "finding_candidates.json",
    }
    _write_json(outputs["ftr_candidates.json"], ftrs)
    _write_json(outputs["review_candidates.json"], reviews)
    _write_json(outputs["finding_candidates.json"], findings)
    print(f"FTR candidates: {len(ftrs)}")
    print(f"Review candidates: {len(reviews)}")
    print(f"Finding candidates: {len(findings)}")
    return outputs


if __name__ == "__main__":
    extract_candidates()
