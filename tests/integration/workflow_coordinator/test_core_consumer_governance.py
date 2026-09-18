"""Committed-core coherence at the pure A1 admission boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.workflow_coordinator.operator import _admit_a1, _selected_ids
from scripts.workflow_coordinator.serialization import (
    component_manifest_from_yaml,
    repository_policy_from_yaml,
    work_item_from_yaml,
    workflow_profile_from_yaml,
)

pytestmark = pytest.mark.ftr("FTR-AGENT-WORKFLOW-COORDINATOR-P5")

REPOSITORY = Path(__file__).resolve().parents[3]
DOGFOOD = REPOSITORY / "docs/ai_info/workflows/dogfood"
A3_RESERVED_PATH = "scripts/workflow_coordinator/resources/agent_operating_contract_v1.txt"


@pytest.mark.parametrize(
    ("bundle_name", "expected_governing_count"),
    [
        ("dmc_fk_c3_wi02", 9),
        ("ior04_formula_sink_capability", 8),
    ],
)
def test_current_core_consumer_bundle_is_admitted_by_its_v2_policy(
    bundle_name, expected_governing_count
):
    bundle = DOGFOOD / bundle_name
    supplied = {
        name: bundle / filename
        for name, filename in (
            ("work_item", "work_item.yaml"),
            ("profile", "profile.yaml"),
            ("policy", "repository_policy.yaml"),
            ("components", "components.yaml"),
            ("task", "task.txt"),
        )
    }
    texts = {name: path.read_text(encoding="utf-8") for name, path in supplied.items()}
    item = work_item_from_yaml(texts["work_item"])
    profile = workflow_profile_from_yaml(texts["profile"])
    policy = repository_policy_from_yaml(texts["policy"])
    manifest = component_manifest_from_yaml(texts["components"])
    selected_component_paths = tuple(
        manifest[component_id].path for component_id in _selected_ids(profile)
    )
    governing_paths = (
        tuple(path.relative_to(REPOSITORY).as_posix() for path in supplied.values())
        + selected_component_paths
    )

    assert len(governing_paths) == expected_governing_count
    assert {"docs/ai_info", A3_RESERVED_PATH} <= set(policy.governance_paths)
    assert policy.work_item_scope_ceiling == item.scope
    assert policy.max_autonomous_hops == item.max_autonomous_hops

    _admit_a1(item, profile, policy, governing_paths)
