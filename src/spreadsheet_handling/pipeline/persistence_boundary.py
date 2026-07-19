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
* top-level ``frame_lifecycle`` -- obsolete generic frame ontology retained
  only as ignored legacy input,
* top-level ``__*``-prefixed keys -- carrier / derived view markers that the
  IR rendering passes own,
* Resolution facets under canonical roots (added by
  ``BUG-CROSS-CARRIER-META-ROUNDTRIP-P4A``):

  - ``legend_blocks[*].resolved`` -- coordinates frozen by
    ``rendering/composer/layout_composer.py::_resolve_legend_position``,
  - ``xref_crosstable[*].dense_axes.resolved`` -- snapshot of the
    columns/rows materialised from current data,
  - ``xref_crosstable[*].column_keys`` -- the same snapshot mirrored at
    the top of the entry.

  Rule wording: the persistence boundary preserves *Intent* and drops
  *Resolution*. Intent is a declarative, backend-neutral value (e.g.
  ``legend_blocks[*].placement``, ``xref_crosstable[*].dense_axes.columns_from``).
  Resolution is materialised from current data, current layout, or
  current pipeline state on every run. Provenance markers
  (``source: workbook``, ``produced_by``) ride alongside Intent and are
  neither Intent nor Resolution -- they are out of scope for this slice.

Out of scope (explicit non-goals):

* a complete ``_meta`` lifecycle inventory,
* using the meta registry as a runtime contract,
* a generic ``persisted_by_default`` field,
* a broader redesign of ``helper_policies``,
* migrating historical ``_meta.yaml`` content beyond the minimum needed,
* read-side sanitisation of sidecars already on disk,
* pruning ``sheets[*].helper_columns`` -- the declared-vs-resolved
  question lives with FTR-FK-HELPER-POLICY-LIFECYCLE-P4A,
* pruning the ``source: workbook`` envelope on the four presentation
  families (carrier-authoritative by policy under
  FTR-PRESENTATION-META-CARRIER-AUTHORITY-P5).

These items are tracked separately in
``docs/backlog/FTR-FK-HELPER-POLICY-LIFECYCLE-P4A.adoc`` and
``docs/backlog/FTR-META-LIFECYCLE-INVENTORY-P5.adoc``.

FK-helper relations are durable (FK Helper Slice 2)
---------------------------------------------------

``helper_policies`` is no longer projected at this boundary. As of FK Helper
Slice 2 (v1 retirement), ``configure_fk_helpers`` writes only the durable v2
relation model and no longer emits the legacy v1 per-target dict. v2 relations
-- whether produced by ``configure_fk_helpers``, ``infer_fk_relations``, or
hand-authored -- are durable declarations that must survive the boundary so
reverse-pipeline (reimport) cleanup can identify helper columns without the v1
dict. The boundary therefore preserves ``helper_policies`` unchanged; it no
longer prunes relations by ``produced_by.step``.

``produced_by`` is retained on each relation as provenance and as the
cross-producer conflict key for ``apply_v2_relations``; it no longer drives any
pruning here. ``produced_by.mode: explicit`` still does *not* mean
user-authored canonical metadata -- it only records that the producing step was
invoked explicitly.

The Dino-shaped replay failure that originally motivated pruning
configure-produced relations (``Frame ... must have flat columns`` when a stale
relation re-materialised helpers onto an unintended frame) is now contained at
the materialisation point: ``enrich_helpers`` preserves the source frame's
column flatness, so a durable relation can no longer turn a flat frame into a
non-flat one. See
``audit/fk_helper_slice2_v1_retirement_review.adoc``.
"""

from __future__ import annotations

from typing import Any, Mapping

RUNTIME_ONLY_TOP_LEVEL_META_KEYS: frozenset[str] = frozenset(
    {"derived", "frame_lifecycle", "pipeline_cleanup"}
)
"""Top-level ``_meta`` keys that must never survive into persistence.

This set also includes obsolete generic metadata that may arrive in a legacy
payload but must not be written again. The full classification belongs to
``FTR-META-LIFECYCLE-INVENTORY-P5``; until then, new producers that emit
runtime-only meta on a new top-level key should extend this set.

``pipeline_cleanup`` is a command family consumed by the orchestrator's
implicit final domain cleanup (``domain/pipeline_cleanup.py``) before this
projection runs; stripping it here is defense in depth for callers that
persist frames without going through the orchestrator, so cleanup commands
can never roundtrip through a carrier and re-execute.
"""


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
        if key == "legend_blocks":
            projected[key] = _project_legend_blocks(value)
            continue
        if key == "xref_crosstable":
            projected[key] = _project_xref_crosstable(value)
            continue
        projected[key] = value

    return projected


def _project_legend_blocks(legend_blocks: Any) -> Any:
    """Strip ``resolved`` Resolution facet from each legend block.

    The ``resolved`` sub-key holds layout coordinates written by
    ``rendering/composer/layout_composer.py::_resolve_legend_position``;
    they are recomputed on every render. The legend's Intent facets
    (``title``, ``entries``, ``placement``, ``target``) are preserved.
    """
    if not isinstance(legend_blocks, Mapping):
        return legend_blocks

    projected: dict[str, Any] = {}
    for name, block in legend_blocks.items():
        if isinstance(block, Mapping) and "resolved" in block:
            projected[name] = {k: v for k, v in block.items() if k != "resolved"}
        else:
            projected[name] = block
    return projected


def _project_xref_crosstable(xref_crosstable: Any) -> Any:
    """Strip Resolution facets from each xref_crosstable entry.

    Two facets are removed:

    * ``column_keys`` -- the concrete column-key list materialised from
      the current value of the source frame's key column.
    * ``dense_axes.resolved`` -- the same snapshot mirrored under
      ``dense_axes``.

    Intent fields (``column_key``, ``row_keys``, ``value``, ``relation``,
    ``matrix``, ``operation``, ``drop_empty``, ``dense_axes.columns_from``,
    ``dense_axes.rows_from``) are preserved.
    """
    if not isinstance(xref_crosstable, Mapping):
        return xref_crosstable

    projected: dict[str, Any] = {}
    for name, entry in xref_crosstable.items():
        if not isinstance(entry, Mapping):
            projected[name] = entry
            continue
        cleaned = {k: v for k, v in entry.items() if k != "column_keys"}
        dense_axes = cleaned.get("dense_axes")
        if isinstance(dense_axes, Mapping) and "resolved" in dense_axes:
            cleaned["dense_axes"] = {k: v for k, v in dense_axes.items() if k != "resolved"}
        projected[name] = cleaned
    return projected


__all__ = [
    "RUNTIME_ONLY_TOP_LEVEL_META_KEYS",
    "project_meta_to_persistable_contract",
]
