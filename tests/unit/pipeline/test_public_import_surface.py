from __future__ import annotations

import importlib.util

import pytest

import spreadsheet_handling.pipeline as public_pipeline
from spreadsheet_handling.pipeline.registry import build_steps_from_config, run_pipeline
from spreadsheet_handling.pipeline.steps import make_bootstrap_meta_step
from spreadsheet_handling.pipeline.types import BoundStep, StepRegistration


pytestmark = [
    pytest.mark.ftr("FTR-PIPELINE-FACADE-AND-SIMPLE-CLI-CLEANUP-P4A"),
    pytest.mark.ftr("FTR-REVIEW-001-QUICK-WINS-P3"),
]


def test_legacy_pipeline_facade_module_is_removed() -> None:
    assert importlib.util.find_spec("spreadsheet_handling.pipeline.pipeline") is None


def test_package_pipeline_exports_only_intentional_public_surface() -> None:
    public_names = set(public_pipeline.__all__)

    assert "build_steps_from_config" in public_names
    assert "build_steps_from_yaml" in public_names
    assert "run_pipeline" in public_names
    assert "BoundStep" in public_names
    assert "StepRegistration" in public_names

    assert "make_reorder_helpers_step" not in public_names
    assert "make_add_validations_step" not in public_names


def test_deleted_header_step_factories_are_not_exposed_by_owning_module() -> None:
    import spreadsheet_handling.pipeline.steps as pipeline_steps

    assert not hasattr(pipeline_steps, "make_flatten_headers_step")
    assert not hasattr(pipeline_steps, "make_unflatten_headers_step")


def test_direct_owning_modules_expose_pipeline_building_blocks() -> None:
    assert callable(build_steps_from_config)
    assert callable(run_pipeline)
    assert callable(make_bootstrap_meta_step)
    assert BoundStep.__name__ == "BoundStep"
    assert StepRegistration.__name__ == "StepRegistration"
