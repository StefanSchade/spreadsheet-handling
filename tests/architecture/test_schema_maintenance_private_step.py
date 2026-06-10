from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from spreadsheet_handling.cli.apps import schema_maintain
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.registry import REGISTRY

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def test_private_schema_maintenance_step_is_not_in_pipeline_registry() -> None:
    assert schema_maintain.PRIVATE_STEP_NAME not in REGISTRY


def test_private_schema_maintenance_step_is_not_in_descriptive_registry() -> None:
    registry_path = Path("registries/pipeline_step_registry.json")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    names = {entry["name"] for entry in registry["entries"]}
    runtime_names = {entry["runtime_name"] for entry in registry["entries"]}
    assert schema_maintain.PRIVATE_STEP_NAME not in names
    assert schema_maintain.PRIVATE_STEP_NAME not in runtime_names


def test_private_schema_maintenance_step_is_not_buildable_from_yaml_config() -> None:
    with pytest.raises(KeyError, match=schema_maintain.PRIVATE_STEP_NAME):
        build_steps_from_config([{"step": schema_maintain.PRIVATE_STEP_NAME}])


def test_cli_uses_bound_step_directly_without_config_builder() -> None:
    source = inspect.getsource(schema_maintain)

    assert "BoundStep(" in source
    assert "build_steps_from_config" not in source
    assert "build_steps_from_yaml" not in source
