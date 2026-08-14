"""E4 boundary guard: the execution-state representation is not macro-wired.

FTR-TRUSTED-INGRESS-P4A section 20 ("Do not prematurely implement E5") is
explicit that E4 may classify exact bound invocation authority and construct
role/transition descriptors, but must not yet thread execution-state
authority through the orchestrator, ``run_app``, or ``sheets-run``, nor
enforce anything at pipeline execution time. This guard keeps that boundary
visible: it fails loudly the moment a later change accidentally wires
``pipeline.execution_state`` into macro flow before E5 is independently
authorized to do so.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")

_MACRO_FLOW_MODULES = (
    Path("src/spreadsheet_handling/application/orchestrator.py"),
    Path("src/spreadsheet_handling/pipeline/runner.py"),
    Path("src/spreadsheet_handling/pipeline/execution.py"),
    Path("src/spreadsheet_handling/pipeline/build.py"),
    Path("src/spreadsheet_handling/pipeline/registry.py"),
)


def _imports(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def test_macro_flow_modules_do_not_import_execution_state() -> None:
    violations: list[str] = []
    for module_path in _MACRO_FLOW_MODULES:
        for imported in _imports(module_path):
            if imported == "spreadsheet_handling.pipeline.execution_state" or imported.startswith(
                "spreadsheet_handling.pipeline.execution_state."
            ):
                violations.append(f"{module_path}: {imported}")
    assert violations == []


def test_execution_state_is_not_a_registered_or_descriptive_pipeline_step() -> None:
    from spreadsheet_handling.pipeline.registry import REGISTRY

    candidates = (
        "execution_state",
        "classify_formula_helper_step",
        "classify_grouped_producer_step",
        "classify_expand_grouped_step",
        "classify_artifact_manifest_step",
    )
    for candidate in candidates:
        assert candidate not in REGISTRY

    registry = json.loads(Path("registries/pipeline_step_registry.json").read_text(encoding="utf-8"))
    names = {entry["name"] for entry in registry["entries"]}
    for candidate in candidates:
        assert candidate not in names


def test_execution_state_does_not_import_orchestrator_or_router() -> None:
    package_root = Path("src/spreadsheet_handling/pipeline/execution_state")
    forbidden = (
        "spreadsheet_handling.application",
        "spreadsheet_handling.io_backends",
        "spreadsheet_handling.cli",
        "spreadsheet_handling.pipeline.registry",
        "spreadsheet_handling.pipeline.build",
        "spreadsheet_handling.pipeline.execution",
        "spreadsheet_handling.pipeline.runner",
    )
    violations: list[str] = []
    for path in sorted(package_root.glob("*.py")):
        for imported in _imports(path):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden):
                violations.append(f"{path}:{imported}")
    assert violations == []
