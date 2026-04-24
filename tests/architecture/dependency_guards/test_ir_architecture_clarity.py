"""Dependency guards for the generic IR write path.

This module keeps the generic write-path implementation free of direct XLSX or
OpenPyXL imports. Write-side semantic and contract checks live in the
architecture semantic-invariants and spreadsheet-contract layers instead.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.ftr("FTR-IR-ARCHITECTURE-CLARITY-P3H")

_GENERIC_WRITEPATH_MODULES = [
    "src/spreadsheet_handling/rendering/composer/layout_composer.py",
    "src/spreadsheet_handling/rendering/flow.py",
    "src/spreadsheet_handling/rendering/ir.py",
    "src/spreadsheet_handling/rendering/plan.py",
    "src/spreadsheet_handling/rendering/passes/__init__.py",
    "src/spreadsheet_handling/rendering/passes/core.py",
    "src/spreadsheet_handling/rendering/passes/meta_pass.py",
    "src/spreadsheet_handling/rendering/passes/style_pass.py",
    "src/spreadsheet_handling/rendering/passes/validation_pass.py",
]

_FORBIDDEN_IMPORT_FRAGMENTS = (
    "openpyxl",
    "io_backends.xlsx",
)


def test_generic_write_path_modules_do_not_import_xlsx_or_openpyxl():
    root = Path(__file__).resolve().parents[3]
    violations: list[str] = []

    for rel_path in _GENERIC_WRITEPATH_MODULES:
        module_path = root / rel_path
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                targets = [node.module or ""]

            for target in targets:
                if any(fragment in target for fragment in _FORBIDDEN_IMPORT_FRAGMENTS):
                    violations.append(f"{rel_path}: {target}")

    assert not violations, (
        "Generic write-path modules must stay spreadsheet-neutral:\n" + "\n".join(violations)
    )
