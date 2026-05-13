"""Durable guards for reviewed pipeline step semantics.

These checks keep the descriptive pipeline step registry aligned with metadata
ownership, composite responsibility, plugin extension semantics, and the
linear pipeline runner contract.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
import yaml


pytestmark = pytest.mark.ftr("FTR-PIPELINE-SEMANTICS-GUARDS-P4")


REPO_ROOT = Path(__file__).resolve().parents[3]
STEP_REGISTRY_PATH = (
    REPO_ROOT / "docs" / "internal_guide" / "architecture" / "pipeline_step_registry.json"
)
META_REGISTRY_PATH = (
    REPO_ROOT / "docs" / "internal_guide" / "architecture" / "meta_registry.yaml"
)

PIPELINE_ORCHESTRATION_PATHS = [
    REPO_ROOT / "src" / "spreadsheet_handling" / "pipeline" / "__init__.py",
    REPO_ROOT / "src" / "spreadsheet_handling" / "pipeline" / "build.py",
    REPO_ROOT / "src" / "spreadsheet_handling" / "pipeline" / "execution.py",
    REPO_ROOT / "src" / "spreadsheet_handling" / "pipeline" / "registry.py",
    REPO_ROOT / "src" / "spreadsheet_handling" / "pipeline" / "runner.py",
]

ALLOWED_COMPOSITE_METADATA_POLICIES = {
    "preserve_public",
    "nested",
    "suppressed",
    "none",
    "current_state_unknown",
}

ALLOWED_PLUGIN_LIFECYCLE_MODES = {
    "plugin_or_caller_owned",
    "declared_lifecycle",
    "caller_owned_lifecycle",
    "declared_lifecycle_or_caller_owned",
}


def _load_step_registry() -> dict[str, Any]:
    with STEP_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    assert isinstance(loaded, dict)
    return loaded


def _load_meta_registry_entries() -> dict[str, dict[str, Any]]:
    with META_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return {entry["name"]: entry for entry in loaded["entries"]}


def _entries_by_name() -> dict[str, dict[str, Any]]:
    registry = _load_step_registry()
    return {entry["name"]: entry for entry in registry["entries"]}


def _meta_refs(entry: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    contract = entry["meta_contract"]
    return [
        (direction, ref)
        for direction in ("reads", "writes")
        for ref in contract[direction]
    ]


def test_persistent_step_metadata_roots_are_registered_canonical_meta() -> None:
    meta_entries = _load_meta_registry_entries()

    for step_name, entry in _entries_by_name().items():
        for direction, ref in _meta_refs(entry):
            if ref["persistence"] != "persistent":
                continue

            assert ref["registry_ref"] == ref["root"], (
                f"{step_name} {direction} {ref['path']} must not make the "
                "step registry a second metadata authority; persistent roots "
                "must point at their meta_registry.yaml entry."
            )
            meta_entry = meta_entries.get(ref["registry_ref"])
            assert meta_entry is not None, (
                f"{step_name} {direction} {ref['path']} references unknown "
                f"metadata root {ref['registry_ref']!r}."
            )
            assert meta_entry["layer"] == "meta_canonical", (step_name, direction, ref)
            assert meta_entry["classification"] == "canonical_meta", (
                step_name,
                direction,
                ref,
            )


def test_current_state_meta_contract_gaps_are_structured_and_reviewable() -> None:
    for step_name, entry in _entries_by_name().items():
        for direction, ref in _meta_refs(entry):
            if ref["persistence"] != "current_state_gap":
                continue

            assert ref["registry_ref"] is None, (step_name, direction, ref)
            assert ref["reason"].strip(), (step_name, direction, ref)
            assert ref["follow_up_ftr"].startswith("FTR-"), (step_name, direction, ref)
            assert ref["review_condition"].strip(), (step_name, direction, ref)


def test_auto_parameters_remain_configuration_owned() -> None:
    for step_name, entry in _entries_by_name().items():
        for param_name, param in entry["parameters"].items():
            param_type = str(param.get("type", "")).lower()
            mentions_auto = param_name == "auto" or "auto" in param_type
            if not mentions_auto:
                continue

            assert entry["category"] == "configuration", (
                f"{step_name}.{param_name} exposes auto-style policy. "
                "Heuristic resolution belongs to configuration steps, not "
                "primitive execution."
            )


def test_composite_steps_declare_public_outputs_internal_frames_and_metadata_policy() -> None:
    entries = _entries_by_name()

    for step_name, entry in entries.items():
        if entry["category"] != "composite":
            continue

        frame_contract = entry["frame_contract"]
        assert entry["wrapped_steps"], step_name
        assert frame_contract["writes"] or frame_contract["view_outputs"], step_name
        assert entry.get("composite_metadata_policy") in ALLOWED_COMPOSITE_METADATA_POLICIES, (
            step_name,
            entry.get("composite_metadata_policy"),
        )

        for wrapped_step in entry["wrapped_steps"]:
            assert entries[wrapped_step]["category"] == "primitive", (step_name, wrapped_step)

        for internal_frame in frame_contract["internal_frames"]:
            assert str(internal_frame).startswith("__"), (step_name, internal_frame)
            assert internal_frame not in frame_contract["view_outputs"], (
                step_name,
                internal_frame,
            )


def test_plugin_contract_preserves_extension_and_frame_set_responsibility() -> None:
    plugin_entries = [
        entry for entry in _entries_by_name().values() if entry["category"] == "plugin"
    ]

    assert [entry["name"] for entry in plugin_entries] == ["plugin"]
    plugin_entry = plugin_entries[0]
    contract = plugin_entry["plugin_contract"]

    assert plugin_entry["factory_shape"] == "plugin_factory"
    assert contract["may_change_frame_set"] is True
    assert contract["lifecycle_responsibility"] in ALLOWED_PLUGIN_LIFECYCLE_MODES
    assert "dynamic_plugin_owned" in plugin_entry["frame_contract"]["reads"]
    assert "dynamic_plugin_owned" in plugin_entry["frame_contract"]["writes"]


def test_pipeline_orchestration_does_not_route_on_workbook_payload_metadata() -> None:
    forbidden_payload_tokens = {
        "_meta",
        "frame_lifecycle",
        "workbook_view",
        "workbook_views",
    }

    for path in PIPELINE_ORCHESTRATION_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }

        violations = forbidden_payload_tokens & literals
        assert not violations, (
            f"{path.relative_to(REPO_ROOT)} contains pipeline-routing payload "
            f"token(s) {sorted(violations)}. Pipeline orchestration must stay "
            "linear and config-driven instead of branching on workbook _meta."
        )
