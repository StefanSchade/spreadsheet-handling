from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import tomllib

import pytest

from spreadsheet_handling.application import schema_maintenance as schema_maintenance_app
from spreadsheet_handling.cli.apps import schema_maintain
from spreadsheet_handling.domain.schema_maintenance import SchemaOperationKind
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.registry import REGISTRY

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def test_private_schema_maintenance_step_is_not_in_pipeline_registry() -> None:
    assert schema_maintenance_app.PRIVATE_STEP_NAME not in REGISTRY


def test_private_schema_maintenance_step_is_not_in_descriptive_registry() -> None:
    registry_path = Path("registries/pipeline_step_registry.json")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    names = {entry["name"] for entry in registry["entries"]}
    runtime_names = {entry["runtime_name"] for entry in registry["entries"]}
    assert schema_maintenance_app.PRIVATE_STEP_NAME not in names
    assert schema_maintenance_app.PRIVATE_STEP_NAME not in runtime_names


def test_private_schema_maintenance_step_is_not_buildable_from_yaml_config() -> None:
    with pytest.raises(KeyError, match=schema_maintenance_app.PRIVATE_STEP_NAME):
        build_steps_from_config([{"step": schema_maintenance_app.PRIVATE_STEP_NAME}])


def test_application_owns_private_bound_step_without_config_builder() -> None:
    source = inspect.getsource(schema_maintenance_app)

    assert "BoundStep(" in source
    assert "build_steps_from_config" not in source
    assert "build_steps_from_yaml" not in source


def test_cli_delegates_schema_maintenance_to_application() -> None:
    source = inspect.getsource(schema_maintain)

    assert "run_schema_maintenance(" in source
    assert "BoundStep(" not in source
    assert "orchestrate(" not in source


def test_domain_schema_maintenance_does_not_import_forbidden_layers() -> None:
    package_root = Path("src/spreadsheet_handling/domain/schema_maintenance")
    forbidden = (
        "spreadsheet_handling.io_backends",
        "spreadsheet_handling.cli",
        "spreadsheet_handling.pipeline.registry",
        "spreadsheet_handling.pipeline.build",
        "spreadsheet_handling.pipeline.types",
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
                if any(name == blocked or name.startswith(f"{blocked}.") for blocked in forbidden):
                    violations.append(f"{path}:{node.lineno}: {name}")

    assert violations == []


def test_schema_maintenance_cli_public_surface_is_documented() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    interfaces = Path("docs/ai_info/interfaces_and_gates.adoc").read_text(encoding="utf-8")

    assert (
        scripts["sheets-schema-maintain"]
        == "spreadsheet_handling.cli.apps.schema_maintain:cli_entry"
    )
    assert "sheets-schema-maintain" in interfaces
    for flag in (
        "--op",
        "--frame",
        "--source-column",
        "--target-column",
        "--default",
        "--insert-before",
        "--insert-after",
        "--column",
        "--reorder-mode",
        "--prune",
        "--dry-run",
        "--write",
        "--report",
        "--in-kind",
        "--in-path",
        "--out-kind",
        "--out-path",
    ):
        assert flag in interfaces


def test_schema_maintenance_operation_values_are_documented() -> None:
    documented = "\n".join(
        [
            Path("docs/release_notes/release_notes.adoc").read_text(encoding="utf-8"),
            Path("docs/user_guide/ch02_workflow/01_workflow.adoc").read_text(encoding="utf-8"),
        ]
    )

    for kind in SchemaOperationKind:
        assert kind.value in documented
