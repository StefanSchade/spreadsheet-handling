"""Architecture guards for the internal ``domain.ingress`` boundary.

Mirrors the schema-maintenance private-step pattern: ingress is framework-owned
macro flow, not a user-configurable pipeline step. It must be absent from both
the runtime and descriptive step registries, must not be YAML-buildable, must
not import forbidden higher layers, and must expose its ordered rule sequence.
See FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from spreadsheet_handling.application import orchestrator
from spreadsheet_handling.domain import ingress as ingress_pkg
from spreadsheet_handling.domain import meta_bootstrap, yaml_overrides
from spreadsheet_handling.domain.ingress import INGRESS_RULES, run_domain_ingress
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.registry import REGISTRY

pytestmark = pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")

# Names by which someone might try to reach ingress as a step.
_INGRESS_STEP_CANDIDATES = (
    "run_domain_ingress",
    "domain_ingress",
    "ingress",
    "legend_blocks_shape",
    "normalize_legend_blocks_shape",
)

_INGRESS_PLUGIN_CALLABLES = (
    "spreadsheet_handling.domain.ingress:run_domain_ingress",
    "spreadsheet_handling.domain.ingress.coordinator:run_domain_ingress",
    (
        "spreadsheet_handling.domain.ingress.legend_blocks:"
        "normalize_legend_blocks_shape"
    ),
)

_INGRESS_CONFIGURATION_ROUTES = (
    "plugin",
    "colon_factory",
)


def test_ingress_is_not_in_runtime_pipeline_registry():
    for candidate in _INGRESS_STEP_CANDIDATES:
        assert candidate not in REGISTRY


def test_ingress_is_not_in_descriptive_step_registry():
    registry = json.loads(
        Path("registries/pipeline_step_registry.json").read_text(encoding="utf-8")
    )
    names = {entry["name"] for entry in registry["entries"]}
    runtime_names = {entry["runtime_name"] for entry in registry["entries"]}
    for candidate in _INGRESS_STEP_CANDIDATES:
        assert candidate not in names
        assert candidate not in runtime_names


def test_ingress_is_not_buildable_from_yaml_config():
    for candidate in _INGRESS_STEP_CANDIDATES:
        with pytest.raises(KeyError, match="Unknown step"):
            build_steps_from_config([{"step": candidate}])


@pytest.mark.parametrize("dotted", _INGRESS_PLUGIN_CALLABLES)
@pytest.mark.parametrize("route", _INGRESS_CONFIGURATION_ROUTES)
def test_ingress_namespace_is_not_addressable_through_yaml_routes(dotted, route):
    spec = (
        {"step": "plugin", "dotted": dotted}
        if route == "plugin"
        else {"step": dotted, "frames": {"_meta": {"legend_blocks": None}}}
    )
    with pytest.raises(
        ValueError,
        match="framework-internal and not configuration/plugin-addressable",
    ):
        build_steps_from_config([spec])


def test_ingress_callable_is_not_reexported_through_invocation_modules():
    # Import the package namespace at call sites so the coordinator does not
    # acquire alternate dotted-callable plugin paths as an incidental alias.
    assert not hasattr(orchestrator, "run_domain_ingress")
    assert not hasattr(meta_bootstrap, "run_domain_ingress")
    assert not hasattr(yaml_overrides, "run_domain_ingress")


def test_domain_ingress_does_not_import_forbidden_layers():
    package_root = Path("src/spreadsheet_handling/domain/ingress")
    forbidden = (
        "spreadsheet_handling.io_backends",
        "spreadsheet_handling.cli",
        "spreadsheet_handling.application",
        "spreadsheet_handling.pipeline.registry",
        "spreadsheet_handling.pipeline.build",
    )
    violations: list[str] = []
    for path in sorted(package_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for name in imported:
                if any(name == b or name.startswith(f"{b}.") for b in forbidden):
                    violations.append(f"{path}:{node.lineno}: {name}")
    assert violations == []


def test_ingress_exposes_ordered_rule_sequence():
    # The coordinator's rule sequence is a visible, ordered tuple so later
    # ingress normalizations extend it explicitly rather than hiding logic in
    # the orchestrator.
    assert isinstance(INGRESS_RULES, tuple)
    assert INGRESS_RULES
    assert all(callable(rule.apply) and rule.name for rule in INGRESS_RULES)
    assert callable(run_domain_ingress)
    assert hasattr(ingress_pkg, "run_domain_ingress")
