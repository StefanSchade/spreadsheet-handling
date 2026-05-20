"""Guard pipeline registry targets for package-root transformation APIs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spreadsheet_handling.pipeline.registry import REGISTRY
from spreadsheet_handling.pipeline.types import StepRegistration

pytestmark = pytest.mark.ftr("FTR-DOMAIN-TRANSFORMATION-PACKAGE-BOUNDARY-GUARDS-P5")


REPO_ROOT = Path(__file__).resolve().parents[3]
STEP_REGISTRY_PATH = (
    REPO_ROOT
    / "docs"
    / "technical_model"
    / "ch05_registries"
    / "pipeline_step_registry"
    / "pipeline_step_registry.json"
)

GUARDED_FAMILY_ROOTS = (
    "spreadsheet_handling.domain.transformations.fk_helpers",
    "spreadsheet_handling.domain.transformations.discriminator_split",
)


def _registry_targets() -> dict[str, str]:
    return {
        step_name: entry.target
        for step_name, entry in REGISTRY.items()
        if isinstance(entry, StepRegistration) and entry.target is not None
    }


def _doc_targets() -> dict[str, str]:
    with STEP_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    return {
        entry["name"]: entry["target"]
        for entry in loaded["entries"]
        if isinstance(entry.get("target"), str)
    }


def _violations(label: str, targets: dict[str, str]) -> list[str]:
    violations: list[str] = []

    for step_name, target in targets.items():
        module_path, _, _ = target.partition(":")
        for family_root in GUARDED_FAMILY_ROOTS:
            if not module_path.startswith(family_root):
                continue
            if module_path != family_root:
                violations.append(
                    f"{label} step {step_name} targets {target}; "
                    f"use {family_root}:<public_function>."
                )
    return violations


def test_runtime_registry_targets_use_package_roots() -> None:
    violations = _violations("runtime", _registry_targets())
    assert not violations, "Pipeline runtime registry target violations:\n" + "\n".join(violations)


def test_documented_registry_targets_use_package_roots() -> None:
    violations = _violations("documented", _doc_targets())
    assert not violations, "Pipeline step registry target violations:\n" + "\n".join(violations)
