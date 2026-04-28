"""Architecture guards for the reviewed pipeline step registry artifact."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from spreadsheet_handling.pipeline.registry import REGISTRY
from spreadsheet_handling.pipeline.types import StepRegistration


pytestmark = pytest.mark.ftr("FTR-PIPELINE-STEP-REGISTRY-P4")


REPO_ROOT = Path(__file__).resolve().parents[3]
STEP_REGISTRY_PATH = (
    REPO_ROOT / "docs" / "internal_guide" / "architecture" / "pipeline_step_registry.json"
)
META_REGISTRY_PATH = (
    REPO_ROOT / "docs" / "internal_guide" / "architecture" / "meta_registry.yaml"
)


def _load_step_registry() -> dict[str, Any]:
    with STEP_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    assert isinstance(loaded, dict)
    return loaded


def _load_meta_registry_names() -> set[str]:
    with META_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return {entry["name"] for entry in loaded["entries"]}


def _entries_by_name() -> dict[str, dict[str, Any]]:
    registry = _load_step_registry()
    return {entry["name"]: entry for entry in registry["entries"]}


def _contract_sets(registry: dict[str, Any]) -> dict[str, set[str]]:
    contract = registry["maintenance_contract"]
    return {
        "required": set(contract["common_required_step_fields"]),
        "categories": set(contract["allowed_categories"]),
        "statuses": set(contract["allowed_statuses"]),
        "factory_shapes": set(contract["allowed_factory_shapes"]),
        "parameter_source_kinds": set(contract["allowed_parameter_source_kinds"]),
        "inverse_kinds": set(contract["allowed_inverse_kinds"]),
        "meta_persistence": set(contract["allowed_meta_persistence"]),
    }


def test_pipeline_step_registry_is_a_review_artifact() -> None:
    registry = _load_step_registry()

    assert registry["registry_version"] == 1
    assert registry["artifact"] == "pipeline_step_registry"
    assert registry["authority"]["runtime_source_of_truth"].endswith("registry.py::REGISTRY")
    assert registry["authority"]["runtime_binding"] == "forbidden"
    assert registry["authority"]["maintenance_mode"] == "manual_review_artifact"
    assert isinstance(registry["entries"], list)
    assert registry["entries"]


def test_pipeline_step_registry_covers_runtime_registry_exactly() -> None:
    registry = _load_step_registry()
    entries = _entries_by_name()

    assert len(entries) == len(registry["entries"])
    assert set(entries) == set(REGISTRY)
    assert {entry["runtime_name"] for entry in entries.values()} == set(REGISTRY)


def test_pipeline_step_registry_entries_have_required_shape_and_enums() -> None:
    registry = _load_step_registry()
    contract = _contract_sets(registry)

    for entry in registry["entries"]:
        assert contract["required"] <= set(entry), entry["name"]
        assert entry["name"] == entry["runtime_name"]
        assert entry["category"] in contract["categories"]
        assert entry["status"] in contract["statuses"]
        assert entry["factory_shape"] in contract["factory_shapes"]
        assert isinstance(entry["purpose"], str) and entry["purpose"].strip()
        assert isinstance(entry["parameters"], dict)
        assert isinstance(entry["wrapped_steps"], list)
        assert isinstance(entry["aliases"], list)

        for parameter_name, parameter in entry["parameters"].items():
            assert isinstance(parameter, dict), (entry["name"], parameter_name)
            assert {"required", "type", "source_kind"} <= set(parameter), (
                entry["name"],
                parameter_name,
            )
            assert parameter["source_kind"] in contract["parameter_source_kinds"], (
                entry["name"],
                parameter_name,
            )

        inverse = entry["inverse"]
        assert inverse["kind"] in contract["inverse_kinds"], entry["name"]
        assert "inverse_step" in inverse
        assert isinstance(inverse["reason"], str) and inverse["reason"].strip()

        frame_contract = entry["frame_contract"]
        assert {
            "reads",
            "writes",
            "preserves",
            "replaces",
            "drops",
            "internal_frames",
            "view_outputs",
        } <= set(frame_contract), entry["name"]
        for field_name, value in frame_contract.items():
            assert isinstance(value, list), (entry["name"], field_name)


def test_pipeline_step_registry_resolves_runtime_targets() -> None:
    entries = _entries_by_name()

    for name, entry in entries.items():
        runtime_entry = REGISTRY[name]
        if isinstance(runtime_entry, StepRegistration):
            assert entry["target"] == runtime_entry.target
            assert entry["factory_shape"] in {"builder_target", "frames_target"}
        else:
            assert entry["target"] is None
            assert entry["factory_shape"] in {"plain_factory", "plugin_factory"}


def test_pipeline_step_registry_composites_declare_resolving_wrapped_steps() -> None:
    entries = _entries_by_name()

    for name, entry in entries.items():
        if entry["category"] != "composite":
            assert entry["wrapped_steps"] == [], name
            continue

        assert entry["wrapped_steps"], name
        for wrapped_step in entry["wrapped_steps"]:
            assert wrapped_step in entries, (name, wrapped_step)


def test_pipeline_step_registry_aliases_are_structured_and_release_bounded() -> None:
    entries = _entries_by_name()

    for entry in entries.values():
        for alias in entry["aliases"]:
            assert isinstance(alias, dict), entry["name"]
            assert "name" in alias
            assert "status" in alias
            if alias["status"] == "deprecated_alias":
                assert "warn_until" in alias
                assert "remove_after" in alias


@pytest.mark.ftr("FTR-PIPELINE-STEP-NAMING-P4")
def test_pipeline_step_registry_tracks_replaced_names_without_runtime_aliases() -> None:
    entries = _entries_by_name()
    expected_replacements = {
        "add_fk_helpers": "apply_fks",
        "remove_fk_helpers": "drop_helpers",
        "validate_fk_helpers": "check_fk_helpers",
        "reorder_fk_helpers": "reorder_helpers",
        "add_lookup_helpers": "enrich_lookup",
    }

    for current_name, replaced_name in expected_replacements.items():
        assert entries[current_name]["replaces"] == [replaced_name]
        assert replaced_name not in entries
        assert replaced_name not in REGISTRY


def test_pipeline_step_registry_meta_contract_references_meta_registry() -> None:
    registry = _load_step_registry()
    contract = _contract_sets(registry)
    meta_registry_names = _load_meta_registry_names()

    for entry in registry["entries"]:
        for direction in ("reads", "writes"):
            refs = entry["meta_contract"][direction]
            assert isinstance(refs, list), (entry["name"], direction)
            for ref in refs:
                assert {"path", "root", "persistence", "registry_ref"} <= set(ref), (
                    entry["name"],
                    direction,
                    ref,
                )
                assert ref["persistence"] in contract["meta_persistence"], (
                    entry["name"],
                    direction,
                    ref,
                )
                if ref["persistence"] == "persistent":
                    assert ref["registry_ref"] in meta_registry_names, (
                        entry["name"],
                        direction,
                        ref,
                    )
                else:
                    assert "reason" in ref and ref["reason"], (entry["name"], direction, ref)
