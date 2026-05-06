#!/usr/bin/env python3
"""Repository-local source-style guardrails.

The checks in this tool protect reviewability. They intentionally stay separate
from architecture guards, which protect layer boundaries and semantic contracts.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_SCAN_ROOTS = (
    "src/spreadsheet_handling",
    "tests/unit",
    "tests/integration",
    "tests/architecture",
)
EXCLUDED_PARTS = {
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv_win",
    "build",
    "dist",
    "tmp",
}

PRODUCTION_FUNCTION_MAX_LINES = 80
TEST_FUNCTION_MAX_LINES = 120
MAX_BRANCH_COMPLEXITY = 12
MAX_IFEXP_DEPTH = 1
MAX_COMPREHENSION_GENERATORS = 2
MAX_COMPREHENSION_FILTERS = 1

ERROR_RULES = {
    "nested-conditional-expression",
    "german-source-comment",
    "parse-error",
    "allowlist-invalid",
}

GERMAN_COMMENT_RE = re.compile(
    r"[ÄÖÜäöüß]|"
    r"\b("
    r"aber|auch|auf|aus|beim|bewusst|datei|fehler|fuer|für|hinweis|hilfe|"
    r"hilfs|kann|keine|nicht|oder|soll|wenn|ziel|quelle|spalte|zeile|wert|"
    r"werte|zurueck|zurück|prüf|pruef"
    r")\b",
    re.IGNORECASE,
)
GERMAN_STRING_RE = re.compile(
    r"[ÄÖÜäöüß]|\b(nicht|keine|ungueltig|ungültig|blattname|spalten)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    path: str
    line: int
    symbol: str
    message: str

    def display(self) -> str:
        symbol = f" [{self.symbol}]" if self.symbol else ""
        return f"{self.severity} {self.rule} {self.path}:{self.line}{symbol}: {self.message}"


@dataclass(frozen=True)
class AllowlistEntry:
    rule: str
    path: str
    symbol: str
    line: int | None
    rationale: str
    owner: str
    review_date: str

    def matches(self, finding: Finding) -> bool:
        if self.rule != finding.rule or self.path != finding.path:
            return False
        if self.symbol and self.symbol != finding.symbol:
            return False
        if self.line is not None and self.line != finding.line:
            return False
        return True


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _rel_path(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _iter_python_files(repo_root: Path, roots: Sequence[str]) -> list[Path]:
    paths: list[Path] = []
    for root_name in roots:
        root = repo_root / root_name
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob("*.py")
        for path in candidates:
            rel_parts = path.resolve().relative_to(repo_root.resolve()).parts
            if any(part in EXCLUDED_PARTS for part in rel_parts):
                continue
            paths.append(path)
    return sorted(set(paths))


def _severity(rule: str) -> str:
    return "ERROR" if rule in ERROR_RULES else "WARN"


def _parse_tree(path: Path, rel_path: str) -> tuple[ast.AST | None, list[Finding]]:
    try:
        text = path.read_text(encoding="utf-8")
        return ast.parse(text, filename=rel_path), []
    except SyntaxError as exc:
        return None, [
            Finding(
                rule="parse-error",
                severity="ERROR",
                path=rel_path,
                line=exc.lineno or 1,
                symbol="",
                message=str(exc),
            )
        ]


class _ComplexityCounter(ast.NodeVisitor):
    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.score = 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            for child in node.body:
                self.visit(child)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            for child in node.body:
                self.visit(child)

    def visit_If(self, node: ast.If) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.score += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.score += 1 + len(node.ifs)
        self.generic_visit(node)


def _branch_complexity(node: ast.AST) -> int:
    counter = _ComplexityCounter(node)
    counter.visit(node)
    return counter.score


def _ifexp_depth(node: ast.AST) -> int:
    if isinstance(node, ast.IfExp):
        return 1 + max(_ifexp_depth(node.test), _ifexp_depth(node.body), _ifexp_depth(node.orelse))
    return max((_ifexp_depth(child) for child in ast.iter_child_nodes(node)), default=0)


class _StyleVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, is_test: bool) -> None:
        self.rel_path = rel_path
        self.is_test = is_test
        self.findings: list[Finding] = []
        self.class_stack: list[str] = []
        self.current_symbol = ""

    @property
    def is_production(self) -> bool:
        return not self.is_test

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        symbol_parts = [*self.class_stack, node.name]
        symbol = ".".join(symbol_parts)
        max_lines = TEST_FUNCTION_MAX_LINES if self.is_test else PRODUCTION_FUNCTION_MAX_LINES
        if node.end_lineno is not None:
            line_count = node.end_lineno - node.lineno + 1
            if line_count > max_lines:
                self.findings.append(
                    Finding(
                        rule="function-length",
                        severity="WARN",
                        path=self.rel_path,
                        line=node.lineno,
                        symbol=symbol,
                        message=f"{line_count} lines exceeds threshold {max_lines}",
                    )
                )

        complexity = _branch_complexity(node)
        if complexity > MAX_BRANCH_COMPLEXITY:
            self.findings.append(
                Finding(
                    rule="branch-complexity",
                    severity="WARN",
                    path=self.rel_path,
                    line=node.lineno,
                    symbol=symbol,
                    message=f"complexity {complexity} exceeds threshold {MAX_BRANCH_COMPLEXITY}",
                )
            )

        previous_symbol = self.current_symbol
        self.current_symbol = symbol
        for child in node.body:
            self.visit(child)
        self.current_symbol = previous_symbol

    def visit_IfExp(self, node: ast.IfExp) -> None:
        if self.is_production:
            depth = _ifexp_depth(node)
            if depth > MAX_IFEXP_DEPTH:
                self.findings.append(
                    Finding(
                        rule="nested-conditional-expression",
                        severity="ERROR",
                        path=self.rel_path,
                        line=node.lineno,
                        symbol=self.current_symbol,
                        message=f"conditional expression depth {depth} exceeds {MAX_IFEXP_DEPTH}",
                    )
                )
                return
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._check_comprehension(node)
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._check_comprehension(node)
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._check_comprehension(node)
        self.generic_visit(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._check_comprehension(node)
        self.generic_visit(node)

    def _check_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    ) -> None:
        if not self.is_production:
            return
        generator_count = len(node.generators)
        filter_count = sum(len(generator.ifs) for generator in node.generators)
        if (
            generator_count > MAX_COMPREHENSION_GENERATORS
            or filter_count > MAX_COMPREHENSION_FILTERS
        ):
            self.findings.append(
                Finding(
                    rule="dense-comprehension",
                    severity="WARN",
                    path=self.rel_path,
                    line=node.lineno,
                    symbol=self.current_symbol,
                    message=(
                        f"{generator_count} generator(s), {filter_count} filter(s) "
                        f"exceeds thresholds {MAX_COMPREHENSION_GENERATORS}/"
                        f"{MAX_COMPREHENSION_FILTERS}"
                    ),
                )
            )

    def visit_Constant(self, node: ast.Constant) -> None:
        if self.is_production and isinstance(node.value, str) and GERMAN_STRING_RE.search(node.value):
            self.findings.append(
                Finding(
                    rule="german-source-string",
                    severity="WARN",
                    path=self.rel_path,
                    line=node.lineno,
                    symbol=self.current_symbol,
                    message="possible German repository-facing string",
                )
            )
        self.generic_visit(node)


def _comment_findings(path: Path, rel_path: str) -> list[Finding]:
    findings: list[Finding] = []
    text = path.read_text(encoding="utf-8")
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        if not GERMAN_COMMENT_RE.search(token.string):
            continue
        findings.append(
            Finding(
                rule="german-source-comment",
                severity="ERROR",
                path=rel_path,
                line=token.start[0],
                symbol="",
                message="possible German repository-facing comment",
            )
        )
    return findings


def collect_findings(repo_root: Path, roots: Sequence[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_python_files(repo_root, roots):
        rel_path = _rel_path(path, repo_root)
        is_test = rel_path.startswith("tests/")
        findings.extend(_comment_findings(path, rel_path))
        tree, parse_findings = _parse_tree(path, rel_path)
        findings.extend(parse_findings)
        if tree is None:
            continue
        visitor = _StyleVisitor(rel_path=rel_path, is_test=is_test)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    return sorted(findings, key=lambda item: (item.severity, item.path, item.line, item.rule, item.symbol))


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return _load_simple_allowlist_yaml(path)

    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return data or {}


def _load_simple_allowlist_yaml(path: Path) -> dict[str, Any]:
    """Parse the narrow allowlist YAML subset used by this repository.

    This keeps the guard command usable before dev dependencies are installed.
    The fallback supports comments, `entries:`, `- key: value`, and `key: value`
    mappings. Use PyYAML for anything more elaborate.
    """
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "entries:":
            continue
        if stripped.startswith("- "):
            current = {}
            entries.append(current)
            stripped = stripped[2:].strip()
            if not stripped:
                continue
        if current is None:
            raise ValueError(f"unsupported allowlist line without entry: {raw_line!r}")
        if ":" not in stripped:
            raise ValueError(f"unsupported allowlist line: {raw_line!r}")
        key, value = stripped.split(":", 1)
        value = value.strip()
        if value.startswith((">", "|")):
            raise ValueError("folded allowlist values require PyYAML")
        current[key.strip()] = _parse_simple_scalar(value)
    return {"entries": entries}


def _parse_simple_scalar(value: str) -> str | int | None:
    if value == "":
        return ""
    if value in {"null", "None"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.isdigit():
        return int(value)
    return value


def load_allowlist(repo_root: Path, allowlist_path: Path) -> tuple[list[AllowlistEntry], list[Finding]]:
    if not allowlist_path.exists():
        return [], []

    rel_path = _rel_path(allowlist_path, repo_root)
    try:
        data = _load_yaml(allowlist_path)
    except Exception as exc:
        return [], [
            Finding(
                rule="allowlist-invalid",
                severity="ERROR",
                path=rel_path,
                line=1,
                symbol="",
                message=str(exc),
            )
        ]

    raw_entries = data.get("entries", [])
    if not isinstance(raw_entries, list):
        return [], [
            Finding(
                rule="allowlist-invalid",
                severity="ERROR",
                path=rel_path,
                line=1,
                symbol="",
                message="'entries' must be a list",
            )
        ]

    entries: list[AllowlistEntry] = []
    errors: list[Finding] = []
    required_fields = {"rule", "path", "rationale", "owner", "review_date"}
    for index, raw in enumerate(raw_entries, start=1):
        if not isinstance(raw, dict):
            errors.append(
                Finding(
                    rule="allowlist-invalid",
                    severity="ERROR",
                    path=rel_path,
                    line=index,
                    symbol="",
                    message="allowlist entry must be a mapping",
                )
            )
            continue
        missing = sorted(required_fields - set(raw))
        if missing:
            errors.append(
                Finding(
                    rule="allowlist-invalid",
                    severity="ERROR",
                    path=rel_path,
                    line=index,
                    symbol=str(raw.get("symbol", "")),
                    message=f"allowlist entry missing required field(s): {', '.join(missing)}",
                )
            )
            continue
        entries.append(
            AllowlistEntry(
                rule=str(raw["rule"]),
                path=str(raw["path"]),
                symbol=str(raw.get("symbol", "")),
                line=int(raw["line"]) if raw.get("line") is not None else None,
                rationale=str(raw["rationale"]),
                owner=str(raw["owner"]),
                review_date=str(raw["review_date"]),
            )
        )
    return entries, errors


def apply_allowlist(
    findings: Iterable[Finding],
    allowlist: Sequence[AllowlistEntry],
) -> tuple[list[Finding], list[Finding]]:
    active_findings: list[Finding] = []
    allowed_findings: list[Finding] = []
    for finding in findings:
        if any(entry.matches(finding) for entry in allowlist):
            allowed_findings.append(finding)
        else:
            active_findings.append(finding)
    return active_findings, allowed_findings


def stale_allowlist_findings(
    allowlist: Sequence[AllowlistEntry],
    allowed_findings: Sequence[Finding],
    scanned_roots: Sequence[str],
) -> list[Finding]:
    stale: list[Finding] = []
    for entry in allowlist:
        if not _path_is_in_scanned_roots(entry.path, scanned_roots):
            continue
        if any(entry.matches(finding) for finding in allowed_findings):
            continue
        stale.append(
            Finding(
                rule="allowlist-stale",
                severity="WARN",
                path=entry.path,
                line=entry.line or 1,
                symbol=entry.symbol,
                message="allowlist entry no longer matches a current finding",
            )
        )
    return stale


def _path_is_in_scanned_roots(path: str, scanned_roots: Sequence[str]) -> bool:
    for root in scanned_roots:
        normalized = root.rstrip("/")
        if path == normalized or path.startswith(f"{normalized}/"):
            return True
    return False


def _format_report(findings: Sequence[Finding], allowed_count: int) -> str:
    error_count = sum(1 for finding in findings if finding.severity == "ERROR")
    warning_count = sum(1 for finding in findings if finding.severity == "WARN")
    lines = [
        (
            "Source-style guardrails: "
            f"{error_count} error(s), {warning_count} warning(s), "
            f"{allowed_count} allowlisted finding(s)"
        )
    ]
    lines.extend(finding.display() for finding in findings)
    return "\n".join(lines)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repository source-style guardrails.")
    parser.add_argument(
        "--allowlist",
        default="tools/source_style_allowlist.yaml",
        help="Path to the source-style allowlist YAML file.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=list(DEFAULT_SCAN_ROOTS),
        help="Files or directories to scan, relative to the repository root.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = _repo_root()
    allowlist_path = (repo_root / args.allowlist).resolve()

    findings = collect_findings(repo_root, args.paths)
    allowlist, allowlist_errors = load_allowlist(repo_root, allowlist_path)
    active_findings, allowed_findings = apply_allowlist(findings, allowlist)
    active_findings.extend(allowlist_errors)
    active_findings.extend(stale_allowlist_findings(allowlist, allowed_findings, args.paths))
    active_findings = sorted(
        active_findings,
        key=lambda item: (item.severity, item.path, item.line, item.rule, item.symbol),
    )
    print(_format_report(active_findings, allowed_count=len(allowed_findings)))
    return 1 if any(finding.severity == "ERROR" for finding in active_findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
