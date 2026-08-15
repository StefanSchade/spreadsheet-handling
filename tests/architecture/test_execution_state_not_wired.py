"""E4/E5 boundary guard: execution-state wiring is confined to the one macro seam.

FTR-TRUSTED-INGRESS-P4A section 20 ("Do not prematurely implement E5") kept
E4's classify-only representation unreachable from macro flow. Section 23
("E5 -- framework-managed macro wiring") intentionally crosses that boundary,
but only at the *one* framework-owned macro seam,
``application.orchestrator.orchestrate`` (and its own small, named execution
component, ``application.managed_pipeline``) -- every other entry point
(``run_app``, ``sheets-run``, the compatibility shim,
``sheets-schema-maintain``/``run_schema_maintenance``) reaches E5 wiring only
by delegating to that seam, per the FTR's entry-surface table (section 6).

``run_pipeline`` (``pipeline/execution.py``) remains the step-only lower-level
API: it is still called by the macro (once per step, so its own debug/
meta-diff tracing keeps working), but it does not itself import
``execution_state``, gain new parameters, or perform any automatic ingress or
re-establishment -- a caller who reaches it directly, bypassing
``orchestrate``, still receives no automatic guarantee (FTR section 6, the
``run_pipeline`` row). ``pipeline/build.py`` and ``pipeline/registry.py``
(step binding/registration) likewise stay unaware of execution-state.

This guard now proves the *new* contract instead of merely relaxing the old
one: the macro seam positively wires execution-state, while every other
listed module -- including ``run_pipeline`` itself -- still does not.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")

# The one small, named macro execution component that directly imports
# pipeline.execution_state (FTR section 24: "one small, named macro execution
# component... over scattering checks through entry points").
_MACRO_SEAM_MODULE = Path("src/spreadsheet_handling/application/managed_pipeline.py")

# The framework-owned macro seam itself: reaches execution_state only by
# delegating to `managed_pipeline`, never by importing it directly.
_ORCHESTRATOR_MODULE = Path("src/spreadsheet_handling/application/orchestrator.py")

# Step-only / binding-only modules that must stay unaware of execution-state:
# a caller reaching these directly (bypassing `orchestrate`) still receives no
# automatic ingress or re-establishment (FTR section 6, `run_pipeline` row).
_UNWIRED_MODULES = (
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


def _imports_execution_state(module_path: Path) -> bool:
    # Matches both absolute (`spreadsheet_handling.pipeline.execution_state...`)
    # and relative (`ast.ImportFrom.module` omits the package prefix, e.g.
    # `pipeline.execution_state...` for a `from ..pipeline.execution_state
    # import ...` two-levels-up relative import) spellings, since production
    # code under `application/` and `pipeline/` uses relative imports.
    target = "pipeline.execution_state"
    for imported in _imports(module_path):
        if imported == target or imported.endswith(f".{target}"):
            return True
        if imported.startswith(f"{target}.") or f".{target}." in imported:
            return True
    return False


def test_unwired_modules_do_not_import_execution_state() -> None:
    violations = [str(path) for path in _UNWIRED_MODULES if _imports_execution_state(path)]
    assert violations == []


def test_macro_seam_module_imports_execution_state() -> None:
    """Pins the E5 wiring itself: fails if a future change silently unwires it."""
    assert _imports_execution_state(_MACRO_SEAM_MODULE)


def test_orchestrator_reaches_execution_state_only_through_managed_pipeline() -> None:
    """`orchestrator.py` must not import `pipeline.execution_state` directly --
    only its one small, named macro execution component
    (`application.managed_pipeline`) does, keeping the classify/apply
    algorithm in one place rather than scattered across entry points (FTR
    section 24).
    """
    assert not _imports_execution_state(_ORCHESTRATOR_MODULE)
    imported = _imports(_ORCHESTRATOR_MODULE)
    assert any(name.endswith("managed_pipeline") for name in imported)


def test_orchestrator_does_not_import_run_pipeline() -> None:
    """`run_pipeline` internals are unchanged; the macro still calls it (once
    per step, via managed_pipeline), but not by importing it directly into
    `orchestrator.py` itself -- keeping the macro's own step-execution
    entry point (`managed_pipeline.run_managed_steps`) the single place that
    decides how `run_pipeline` is invoked.
    """
    imported = _imports(_ORCHESTRATOR_MODULE)
    assert "spreadsheet_handling.pipeline.execution" not in imported
    assert not any(name.endswith(".pipeline.execution") or name == "pipeline.execution" for name in imported)


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
