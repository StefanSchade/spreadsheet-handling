"""Bounded architecture guards for Phase-E E7 activation ordering."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import spreadsheet_handling.application.orchestrator as orchestrator_module
import spreadsheet_handling.application.schema_maintenance as schema_module
import spreadsheet_handling.cli.apps.run as cli_run_module
import spreadsheet_handling.pipeline.build as build_module
import spreadsheet_handling.pipeline.execution as execution_module
import spreadsheet_handling.pipeline.registry as registry_module
import spreadsheet_handling.pipeline.steps as steps_module
from spreadsheet_handling.pipeline.registry import REGISTRY


pytestmark = [
    pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A"),
    pytest.mark.guardrail,
]


def _resolver_call_owners(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    owners: set[str] = set()
    stack: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "resolve_configuration_callable":
                owners.add(stack[-1] if stack else "<module>")
            self.generic_visit(node)

    Visitor().visit(tree)
    return owners


def test_all_configuration_dotted_activation_sites_are_bounded_and_known() -> None:
    assert _resolver_call_owners(registry_module) == {"resolve_registration"}
    assert _resolver_call_owners(steps_module) == {"_resolve_target", "make_plugin_step"}

    source = inspect.getsource(build_module.build_steps_from_config)
    assert source.index("_authorize_step_spec(") < source.index(
        "_build_trusted_steps_from_config([authorized])"
    )
    authorize_source = inspect.getsource(
        __import__(
            "spreadsheet_handling.pipeline.description_authorization",
            fromlist=["_authorize_step_spec"],
        )._authorize_step_spec
    )
    assert "if step_id not in REGISTRY" in authorize_source
    assert "if \":\" in step_id" in authorize_source
    assert "resolve_registration" not in authorize_source


def test_registry_classification_is_complete_but_not_derived_from_membership() -> None:
    from spreadsheet_handling.pipeline.description_authorization import (
        _REGISTERED_STEP_CLASSIFICATIONS,
    )

    assert set(_REGISTERED_STEP_CLASSIFICATIONS) == set(REGISTRY) - {"plugin"}
    source = inspect.getsource(
        __import__(
            "spreadsheet_handling.pipeline.description_authorization",
            fromlist=["_REGISTERED_STEP_CLASSIFICATIONS"],
        )
    )
    assert "set(REGISTRY)" not in source
    assert "for name in REGISTRY" not in source


def test_orchestrator_has_no_e7_policy_or_raw_description_responsibility() -> None:
    signature = inspect.signature(orchestrator_module.orchestrate)
    assert "step_specs" not in signature.parameters
    assert "description_authorization" not in signature.parameters
    source = inspect.getsource(orchestrator_module)
    assert "description_authorization" not in source
    assert "LessTrustedDescriptionAuthorization" not in source


def test_direct_runner_and_schema_maintenance_do_not_depend_on_e7_policy() -> None:
    assert "description_authorization" not in inspect.getsource(execution_module)
    assert "description_authorization" not in inspect.getsource(schema_module)
    assert "description_authorization" not in inspect.getsource(cli_run_module)


def test_only_expected_runtime_modules_import_e7_authorization() -> None:
    source_root = Path(build_module.__file__).resolve().parents[1]
    importers: set[str] = set()
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "description_authorization import" in text:
            importers.add(path.relative_to(source_root).as_posix())
    assert importers == {
        "pipeline/__init__.py",
        "pipeline/build.py",
        "pipeline/runner.py",
    }
