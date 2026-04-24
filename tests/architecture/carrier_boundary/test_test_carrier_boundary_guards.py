"""Carrier-boundary guards for the normalized test topology.

These checks keep collected tests inside the known carrier roots, prevent
support carriers from silently turning into test carriers, and keep topology
markers path-owned rather than manually encoded in test modules.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.ftr("FTR-TEST-CARRIER-BOUNDARY-GUARDS-P4")


REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_ROOT = REPO_ROOT / "tests"

ACTIVE_CARRIER_ROOTS = ("unit", "integration", "architecture", "legacy_pre_hex")
SUPPORT_CARRIER_ROOTS = ("utils", "data", "experimental")
PATH_OWNED_TOPOLOGY_MARKERS = ("unit", "integ", "arch", "current_state", "legacy", "prehex")


def _iter_python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _iter_pytest_style_test_files() -> list[Path]:
    return sorted(path for path in TESTS_ROOT.rglob("test_*.py") if "__pycache__" not in path.parts)


def _module_tree(module_path: Path) -> ast.AST:
    return ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))


def _collected_symbol_names(module_path: Path) -> list[str]:
    tree = _module_tree(module_path)
    names: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            names.append(node.name)

    return names


def _explicit_pytest_marker_names(module_path: Path) -> list[str]:
    tree = _module_tree(module_path)
    names: list[str] = []

    # This guard catches normal explicit marker usage, not dynamic marker construction.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.value, ast.Attribute):
            continue
        if not isinstance(node.value.value, ast.Name):
            continue
        if node.value.value.id != "pytest":
            continue
        if node.value.attr != "mark":
            continue
        names.append(node.attr)

    return names


def test_pytest_style_tests_live_only_under_known_carrier_roots():
    violations: list[str] = []

    for module_path in _iter_pytest_style_test_files():
        rel_path = module_path.relative_to(TESTS_ROOT)
        carrier_root = rel_path.parts[0] if rel_path.parts else ""
        if carrier_root not in ACTIVE_CARRIER_ROOTS:
            violations.append(rel_path.as_posix())

    assert not violations, (
        "Pytest-style test files must live under the known carrier roots "
        f"{ACTIVE_CARRIER_ROOTS}:\n" + "\n".join(violations)
    )


def test_support_carriers_do_not_define_collected_tests():
    violations: list[str] = []

    for carrier_name in SUPPORT_CARRIER_ROOTS:
        carrier_root = TESTS_ROOT / carrier_name
        for module_path in _iter_python_files(carrier_root):
            collected_symbols = _collected_symbol_names(module_path)
            if not collected_symbols:
                continue
            rel_path = module_path.relative_to(TESTS_ROOT).as_posix()
            violations.append(f"{rel_path}: {', '.join(collected_symbols)}")

    assert not violations, (
        "Support carriers must not define collected tests or Test classes:\n"
        + "\n".join(violations)
    )


def test_topology_markers_are_path_owned_not_written_manually():
    violations: list[str] = []

    for module_path in _iter_pytest_style_test_files():
        rel_path = module_path.relative_to(TESTS_ROOT).as_posix()
        explicit_markers = sorted(
            {
                marker_name
                for marker_name in _explicit_pytest_marker_names(module_path)
                if marker_name in PATH_OWNED_TOPOLOGY_MARKERS
            }
        )
        if explicit_markers:
            violations.append(f"{rel_path}: {', '.join(explicit_markers)}")

    assert not violations, (
        "Topology markers are path-owned and should not be written manually:\n"
        + "\n".join(violations)
    )
