"""Orchestrator-owned projection of runtime ``_meta`` onto persistable form.

This module establishes a narrow persistence boundary between the runtime
``_meta`` shape that pipeline steps produce and consume, and the persistable
``_meta`` contract that gets written out by *any* backend.

Architectural placement
-----------------------

The projection is invoked by the orchestrator immediately before persistence,
between the configured pipeline steps and the saver call:

    load frames + _meta
    merge / bootstrap runtime state
    run configured pipeline steps
    --> project runtime meta to persistable meta contract <-- (this module)
    save output

It is deliberately *not* a public pipeline step in the YAML surface and must
not be auto-appended as one. The persistence boundary is part of the
orchestrator's macro flow, not a transformation the consumer configures.

Carrier neutrality
------------------

The projection applies the same rules regardless of the output backend.
Spreadsheet persistence adds a rendering / layout branch on top of the
persistable meta contract, but the persistable meta itself is carrier
neutral. Structured persistence (json_dir, yaml_dir, xml_dir, csv_dir)
consists of the same persistable meta projection without layout artifacts.
This module exists so that JSON / YAML / XML / CSV directories cannot leak
runtime-only meta where the spreadsheet render flow would have filtered it
implicitly.

Scope of this fix (minimal, release-near)
-----------------------------------------

Pruned:

* top-level ``derived`` -- transient runtime helper-column provenance,
* top-level ``__*``-prefixed keys -- carrier / derived view markers that the
  IR rendering passes own,
* runtime-produced FK-helper v2 relation entries under
  ``helper_policies.fk.relations`` where ``produced_by.step`` equals
  ``configure_fk_helpers``. The remaining ``helper_policies`` structure
  (v1 per-target dicts, user-authored or otherwise non-runtime-produced
  relations) is preserved.

Out of scope (explicit non-goals):

* a complete ``_meta`` lifecycle inventory,
* using the meta registry as a runtime contract,
* a generic ``persisted_by_default`` field,
* a broader redesign of ``helper_policies``,
* migrating historical ``_meta.yaml`` content beyond the minimum needed.

These items are tracked separately in
``docs/backlog/FTR-FK-HELPER-POLICY-LIFECYCLE-P4A.adoc`` and
``docs/backlog/FTR-META-LIFECYCLE-INVENTORY-P5.adoc``.

Note on ``produced_by.mode``
---------------------------

``produced_by.mode: explicit`` does *not* mean user-authored canonical
metadata. It only records that the pipeline step that produced the entry
was invoked explicitly. The content of runtime-produced v2 relations is
compiled pipeline state; replaying it as canonical input on a later run is
what caused the FK helper duplication observed in the worldbuilding
adoption.
"""

from __future__ import annotations

from typing import Any, Mapping

RUNTIME_ONLY_TOP_LEVEL_META_KEYS: frozenset[str] = frozenset({"derived"})
"""Top-level ``_meta`` keys that must never survive into persistence.

Conservative initial set. The full classification belongs to
``FTR-META-LIFECYCLE-INVENTORY-P5``; until then, new producers that emit
runtime-only meta on a new top-level key should extend this set.
"""

_RUNTIME_FK_HELPER_PRODUCER_STEP = "configure_fk_helpers"


def project_meta_to_persistable_contract(meta: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project a runtime ``_meta`` mapping onto its persistable contract.

    Pure function. Returns a new dict; the input mapping is not mutated.

    The rules are intentionally narrow and additive: anything not matched
    by an explicit pruning rule passes through unchanged. Adding a new rule
    is a deliberate decision documented alongside the rule.
    """
    if not isinstance(meta, Mapping):
        return {}

    projected: dict[str, Any] = {}
    for key, value in meta.items():
        if key in RUNTIME_ONLY_TOP_LEVEL_META_KEYS:
            continue
        if isinstance(key, str) and key.startswith("__"):
            # Root-level carrier / derived-view markers. These belong to IR
            # rendering passes and are not part of the persisted contract.
            continue
        if key == "helper_policies":
            projected_helper_policies = _project_helper_policies(value)
            if projected_helper_policies is not None:
                projected[key] = projected_helper_policies
            continue
        projected[key] = value

    return projected


def _project_helper_policies(helper_policies: Any) -> dict[str, Any] | None:
    """Strip runtime-produced FK-helper v2 relation entries.

    Preserves the rest of ``helper_policies`` (lookup namespace, v1
    per-target dicts under ``fk``, manually authored relations). Only the
    narrowly identified runtime carrier is removed.
    """
    if not isinstance(helper_policies, Mapping):
        return helper_policies if helper_policies is not None else None

    projected: dict[str, Any] = dict(helper_policies)
    fk_section = projected.get("fk")
    if not isinstance(fk_section, Mapping):
        return projected

    projected_fk = dict(fk_section)
    relations = projected_fk.get("relations")
    if isinstance(relations, list):
        kept = [entry for entry in relations if not _is_runtime_produced_fk_relation(entry)]
        if kept:
            projected_fk["relations"] = kept
        else:
            # No legitimate relations remain. Drop the empty marker and the
            # paired schema_version, since schema_version on its own only
            # describes the relations envelope and would otherwise be a
            # semantically misleading orphan.
            projected_fk.pop("relations", None)
            projected_fk.pop("schema_version", None)

    projected["fk"] = projected_fk
    return projected


def _is_runtime_produced_fk_relation(entry: Any) -> bool:
    if not isinstance(entry, Mapping):
        return False
    produced_by = entry.get("produced_by")
    if not isinstance(produced_by, Mapping):
        return False
    return produced_by.get("step") == _RUNTIME_FK_HELPER_PRODUCER_STEP


__all__ = [
    "RUNTIME_ONLY_TOP_LEVEL_META_KEYS",
    "project_meta_to_persistable_contract",
]
