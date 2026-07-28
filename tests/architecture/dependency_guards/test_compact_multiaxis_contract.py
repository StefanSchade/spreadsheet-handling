"""Architecture guards for Compact Multiaxis composition ownership."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.ftr("FTR-COMPACT-MULTIAXIS-META-PERSISTENCE-CORRECTION-P5")


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPACT_SOURCE = (
    REPO_ROOT
    / "src"
    / "spreadsheet_handling"
    / "domain"
    / "transformations"
    / "compact_multiaxis.py"
)


def test_compact_multiaxis_has_no_sparse_defaults_dependency() -> None:
    tree = ast.parse(COMPACT_SOURCE.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    called_names: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.append(node.module or "")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.append(node.func.attr)

    assert not any("sparse_defaults" in module for module in imported_modules)
    assert not any(name in {"sparse_collapse", "sparse_expand"} for name in called_names)
