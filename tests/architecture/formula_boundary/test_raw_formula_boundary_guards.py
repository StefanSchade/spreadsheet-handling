"""Formula-boundary guards for backend-specific raw formula leakage.

These checks keep obvious XLSX- or ODS-shaped formula syntax out of generic
layers while leaving concrete adapters and quarantined current-state tests as
the explicit allowed zones for adapter-facing syntax.

This is a conservative source-level drift guard. False positives should usually
be resolved by moving backend syntax behind an adapter or translator boundary
rather than by broad allowlisting.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.ftr("FTR-RAW-FORMULA-BOUNDARY-GUARDS-P4")


REPO_ROOT = Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "src" / "spreadsheet_handling"

SCANNED_GENERIC_PATHS = (
    PKG_ROOT / "core",
    PKG_ROOT / "domain",
    PKG_ROOT / "pipeline",
    PKG_ROOT / "rendering",
    PKG_ROOT / "io_backends" / "spreadsheet_contract.py",
)

# Documented allowed zones; this guard only scans generic paths.
DOCUMENTED_ALLOWED_FORMULA_SYNTAX_PATHS = (
    PKG_ROOT / "io_backends" / "xlsx",
    PKG_ROOT / "io_backends" / "ods",
    REPO_ROOT / "tests" / "architecture" / "current_state",
)

FORBIDDEN_FORMULA_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"=XLOOKUP\(", re.IGNORECASE), "xlsx-xlookup"),
    (re.compile(r"=VLOOKUP\(", re.IGNORECASE), "xlsx-vlookup"),
    (re.compile(r"=SUM\(", re.IGNORECASE), "xlsx-sum"),
    (re.compile(r"=IF\(", re.IGNORECASE), "xlsx-if"),
    (re.compile(r"=[A-Za-z_][A-Za-z0-9_]*!\$?[A-Z]{1,3}\$?\d+", re.IGNORECASE), "a1-sheet-ref"),
    (re.compile(r"of:=", re.IGNORECASE), "ods-openformula-prefix"),
    (re.compile(r"table:formula", re.IGNORECASE), "ods-table-formula"),
    (re.compile(r"openformula", re.IGNORECASE), "openformula-marker"),
    (re.compile(r"oooc:", re.IGNORECASE), "ods-oooc-marker"),
    (re.compile(r"msoxl:", re.IGNORECASE), "xlsx-msoxl-marker"),
)


def _iter_python_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(path for path in target.rglob("*.py") if "__pycache__" not in path.parts)


def _find_formula_hits(module_path: Path) -> list[str]:
    text = module_path.read_text(encoding="utf-8")
    hits: list[str] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, label in FORBIDDEN_FORMULA_PATTERNS:
            if pattern.search(line):
                rel_path = module_path.relative_to(REPO_ROOT).as_posix()
                hits.append(f"{rel_path}:{lineno}: {label}: {line.strip()}")

    return hits


def test_raw_backend_formula_markers_do_not_leak_into_generic_layers():
    violations: list[str] = []

    for target in SCANNED_GENERIC_PATHS:
        for module_path in _iter_python_files(target):
            violations.extend(_find_formula_hits(module_path))

    assert not violations, (
        "Raw backend formula syntax must stay out of generic layers:\n"
        + "\n".join(violations)
    )


def test_formula_boundary_allowed_zones_are_explicit_and_outside_generic_scan():
    for scanned_path in SCANNED_GENERIC_PATHS:
        assert scanned_path.exists(), f"Scanned generic path is missing: {scanned_path}"

    for allowed_path in DOCUMENTED_ALLOWED_FORMULA_SYNTAX_PATHS:
        assert allowed_path.exists(), f"Allowed formula-syntax path is missing: {allowed_path}"

    for scanned_path in SCANNED_GENERIC_PATHS:
        scanned_resolved = scanned_path.resolve()
        for allowed_path in DOCUMENTED_ALLOWED_FORMULA_SYNTAX_PATHS:
            allowed_resolved = allowed_path.resolve()
            assert allowed_resolved != scanned_resolved
            assert scanned_resolved not in allowed_resolved.parents
