"""Narrow guard for the opt-in registry contract lifecycle model.

Validates the structure of ``contract_lifecycle`` blocks on meta registry
entries that opt into the lifecycle vocabulary defined in
``docs/technical_model/ch05_registries/registry_semantics/05_contract_lifecycle.adoc``.

The guard intentionally does **not**:

* require lifecycle fields on entries that have not opted in;
* parse prose fields (``reason``, ``bridge_rule``,
  ``identity_derivation_notes``, ``removal_condition``);
* validate ``pipeline_step_registry.json`` (step-surface transition state
  lives in per-step ``purpose`` plus per-meta-ref ``notes``);
* become a broad metadata schema-validation framework.

It fails for the dangerous cases enumerated by
``FTR-REGISTRY-CONTRACT-LIFECYCLE-MODEL-P5``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.ftr("FTR-REGISTRY-CONTRACT-LIFECYCLE-MODEL-P5")


_FTR_ID_PATTERN = re.compile(r"^FTR-[A-Z0-9][A-Z0-9-]*$")

_ALLOWED_BRIDGE_STATUSES = {"none", "planned", "active", "retired"}
_ALLOWED_BRIDGE_TYPES = {
    "dual_write",
    "dual_read",
    "adapter",
    "mapping",
    "rejection_with_migration_error",
    "manual_review_only",
}
_ALLOWED_IDENTITY_DERIVATIONS = {
    "explicit_new_fields",
    "deterministic_normalization",
    "temporary_bridge",
    "rejection_with_migration_error",
    "no_migration",
    "not_applicable",
}
_ACTIVE_BRIDGE_REQUIRED_FIELDS = (
    "bridge_type",
    "source_shape",
    "target_shape",
    "reason",
    "removal_ftr",
    "removal_condition",
)
_PILOT_ENTRY_NAME = "helper_policies"


def _load_registry() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]
    registry_path = (
        repo_root
        / "docs"
        / "technical_model"
        / "ch05_registries"
        / "meta_registry"
        / "meta_registry.yaml"
    )
    with registry_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return loaded


def _lifecycle_entries() -> list[tuple[str, dict[str, Any]]]:
    registry = _load_registry()
    pairs: list[tuple[str, dict[str, Any]]] = []
    for entry in registry["entries"]:
        lifecycle = entry.get("contract_lifecycle")
        if lifecycle is None:
            continue
        assert isinstance(lifecycle, dict), entry["name"]
        pairs.append((entry["name"], lifecycle))
    return pairs


def test_pilot_entry_opts_in_to_lifecycle_fields() -> None:
    names = {name for name, _ in _lifecycle_entries()}
    assert _PILOT_ENTRY_NAME in names, (
        "Pilot entry helper_policies must declare contract_lifecycle; "
        "FTR-REGISTRY-CONTRACT-LIFECYCLE-MODEL-P5 wires the pilot here."
    )


def test_lifecycle_blocks_have_current_and_target_state() -> None:
    for entry_name, lifecycle in _lifecycle_entries():
        current_state = lifecycle.get("current_state")
        target_state = lifecycle.get("target_state")

        assert isinstance(current_state, dict), entry_name
        assert isinstance(target_state, dict), entry_name

        for field_name in ("runtime_writes", "runtime_reads", "producers", "consumers"):
            value = current_state.get(field_name)
            assert isinstance(value, list) and value, (entry_name, field_name)

        shapes = current_state.get("shapes")
        assert isinstance(shapes, dict) and shapes, entry_name

        assert isinstance(target_state.get("preferred_shape"), str), entry_name
        assert target_state["preferred_shape"].strip(), entry_name
        owning_ftr = target_state.get("owning_ftr")
        assert isinstance(owning_ftr, str), entry_name
        assert _FTR_ID_PATTERN.match(owning_ftr), (entry_name, owning_ftr)


def test_lifecycle_shape_tokens_are_internally_defined() -> None:
    for entry_name, lifecycle in _lifecycle_entries():
        current_state = lifecycle["current_state"]
        defined_shapes = set(current_state["shapes"])
        bridge = lifecycle.get("transition_bridge") or {}

        referenced: list[tuple[str, str]] = []
        for field_name in ("runtime_writes", "runtime_reads"):
            for token in current_state.get(field_name, []):
                referenced.append((field_name, token))
        referenced.append(("target_state.preferred_shape", lifecycle["target_state"]["preferred_shape"]))
        for field_name in ("source_shape", "target_shape"):
            token = bridge.get(field_name)
            if token is not None:
                referenced.append((f"transition_bridge.{field_name}", token))

        for source, token in referenced:
            assert isinstance(token, str), (entry_name, source, token)
            assert token in defined_shapes, (entry_name, source, token, sorted(defined_shapes))


def test_active_bridge_requires_full_structure() -> None:
    for entry_name, lifecycle in _lifecycle_entries():
        bridge = lifecycle.get("transition_bridge")
        if bridge is None:
            continue
        assert isinstance(bridge, dict), entry_name

        status = bridge.get("status")
        assert status in _ALLOWED_BRIDGE_STATUSES, (
            entry_name,
            status,
            "bridge status must use lifecycle vocabulary; capability-profile "
            "terms such as accepted_gap are not allowed here",
        )

        if status != "active":
            continue

        for field_name in _ACTIVE_BRIDGE_REQUIRED_FIELDS:
            value = bridge.get(field_name)
            assert isinstance(value, str) and value.strip(), (entry_name, field_name)

        assert bridge["bridge_type"] in _ALLOWED_BRIDGE_TYPES, (entry_name, bridge["bridge_type"])
        assert _FTR_ID_PATTERN.match(bridge["removal_ftr"]), (entry_name, bridge["removal_ftr"])

        identity_derivation = bridge.get("identity_derivation")
        assert identity_derivation in _ALLOWED_IDENTITY_DERIVATIONS, (
            entry_name,
            identity_derivation,
        )


def test_shape_drift_requires_non_retired_bridge() -> None:
    for entry_name, lifecycle in _lifecycle_entries():
        current_state = lifecycle["current_state"]
        writes = set(current_state["runtime_writes"])
        reads = set(current_state["runtime_reads"])

        if writes == reads:
            continue

        bridge = lifecycle.get("transition_bridge")
        assert isinstance(bridge, dict), (
            entry_name,
            "runtime_writes and runtime_reads diverge; a transition_bridge must be documented",
        )
        assert bridge.get("status") in {"planned", "active"}, (
            entry_name,
            bridge.get("status"),
            "shape drift requires an active or planned bridge",
        )


def test_retired_bridge_does_not_still_read_source_shape() -> None:
    for entry_name, lifecycle in _lifecycle_entries():
        bridge = lifecycle.get("transition_bridge") or {}
        if bridge.get("status") != "retired":
            continue

        source_shape = bridge.get("source_shape")
        runtime_reads = set(lifecycle["current_state"]["runtime_reads"])
        assert source_shape not in runtime_reads, (
            entry_name,
            source_shape,
            "retired bridge must not still describe runtime_reads of source shape",
        )


def test_pilot_helper_policies_fk_current_consumers_match_runtime_truth() -> None:
    """Catch the dangerous case the FTR named: a target-only consumer
    silently appearing under ``current_state.consumers`` and being treated as
    a current runtime reader.

    Until ``FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5`` refactors the
    FK-helper primitives to consume the v2 relation policy, the only current
    runtime reader of ``_meta.helper_policies.fk`` is
    ``domain.transformations.fk_helpers.enrich_helpers``. v2-aware
    primitives (notably ``drop_helpers``) must stay listed under
    ``target_state.target_consumers`` only.

    Pinning the expected current reader and the target-only consumer here
    avoids the false negative of a set-difference check that is true by
    construction.
    """
    registry = _load_registry()
    pilot_entry = next(
        entry for entry in registry["entries"] if entry["name"] == _PILOT_ENTRY_NAME
    )
    lifecycle = pilot_entry["contract_lifecycle"]
    current_consumers = set(lifecycle["current_state"]["consumers"])
    target_consumers = set(lifecycle["target_state"].get("target_consumers") or [])

    expected_current_consumers = {"domain.transformations.fk_helpers.enrich_helpers"}
    target_only_until_primitives_ftr = {
        "domain.transformations.fk_helpers.drop_helpers",
    }

    assert current_consumers == expected_current_consumers, (
        "helper_policies.fk current_state.consumers must reflect runtime truth; "
        "only enrich_helpers consumes v1 today. "
        "FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5 owns adding v2-aware "
        "primitives to the current reader set."
    )

    for target_only_consumer in target_only_until_primitives_ftr:
        assert target_only_consumer not in current_consumers, (
            f"{target_only_consumer} must stay target-only until "
            "FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5 changes runtime behavior"
        )
        assert target_only_consumer in target_consumers, (
            f"{target_only_consumer} should be listed under "
            "target_state.target_consumers while the bridge is active"
        )
