"""Step registry authority for canonical pipeline step names.

Maps step names (strings) to factory functions or registrations. Binding
configuration into executable steps lives in pipeline/build.py.
"""

from __future__ import annotations

import importlib
from typing import Dict

from .types import StepFactory, StepRegistration

from .steps import (
    make_builder_target_step,
    make_frames_target_step,
    make_identity_step,
    make_validate_step,
    make_apply_fks_step,
    make_drop_helpers_step,
    make_check_fk_helpers_step,
    make_plugin_step,
)

REGISTRY: Dict[str, StepRegistration | StepFactory] = {
    "identity": make_identity_step,
    "validate": make_validate_step,
    "add_fk_helpers": make_apply_fks_step,
    "remove_fk_helpers": make_drop_helpers_step,
    "validate_fk_helpers": make_check_fk_helpers_step,
    "plugin": make_plugin_step,
    "flatten_headers": StepRegistration(
        factory=make_builder_target_step,
        target="spreadsheet_handling.domain.transformations.helpers:flatten_headers",
    ),
    "unflatten_headers": StepRegistration(
        factory=make_builder_target_step,
        target="spreadsheet_handling.domain.transformations.helpers:unflatten_headers",
    ),
    "reorder_fk_helpers": StepRegistration(
        factory=make_builder_target_step,
        target="spreadsheet_handling.domain.transformations.helpers:reorder_helpers_next_to_fk",
    ),
    "add_validations": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.validations.validate_columns:add_validations",
    ),
    "validate_references": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.validations.reference_validations:validate_references",
    ),
    "validate_graph": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.validations.graph_validations:validate_graph",
    ),
    "configure_workbook_view": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.workbook_views:configure_workbook_view",
    ),
    "configure_lookup_helpers": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.helper_policies:configure_lookup_helpers",
    ),
    "configure_fk_helpers": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.helper_policies:configure_fk_helpers",
    ),
    "bootstrap_meta": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.meta_bootstrap:bootstrap_meta",
    ),
    "apply_overrides": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.yaml_overrides:load_and_apply_overrides",
    ),
    "write_structured_yaml": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.structured_yaml:write_structured_yaml",
    ),
    "split_by_discriminator": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.discriminator_split:split_by_discriminator",
    ),
    "merge_by_discriminator": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.discriminator_split:merge_by_discriminator",
    ),
    "extract_frame": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.extractions.frame_extract:extract_frame",
    ),
    "pivot_frame": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.tabular_views:pivot_frame",
    ),
    "join_frames": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.join_views:join_frames",
    ),
    "expand_xref": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.xref_crosstable:expand_xref",
    ),
    "contract_xref": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.xref_crosstable:contract_xref",
    ),
    "sparse_collapse": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.sparse_defaults:sparse_collapse",
    ),
    "sparse_expand": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.sparse_defaults:sparse_expand",
    ),
    "normalize_resource_overrides": StepRegistration(
        factory=make_frames_target_step,
        target=(
            "spreadsheet_handling.domain.transformations.resource_overrides:"
            "normalize_resource_overrides"
        ),
    ),
    "decode_cell_values": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.cell_codec:decode_cell_values",
    ),
    "encode_cell_values": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.cell_codec:encode_cell_values",
    ),
    "expand_compact_multiaxis": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.compact_multiaxis:expand_compact_multiaxis",
    ),
    "contract_compact_multiaxis": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.compact_multiaxis:contract_compact_multiaxis",
    ),
    "add_lookup_helpers": StepRegistration(
        factory=make_frames_target_step,
        target="spreadsheet_handling.domain.transformations.enrich_lookup:enrich_lookup",
    ),
    "write_key_value_resources": StepRegistration(
        factory=make_frames_target_step,
        target=(
            "spreadsheet_handling.domain.key_value_writer:"
            "write_key_value_resources"
        ),
    ),
    "write_artifact_manifest": StepRegistration(
        factory=make_frames_target_step,
        target=(
            "spreadsheet_handling.domain.artifact_manifest:"
            "write_artifact_manifest"
        ),
    ),
}


def resolve_registration(step_id: str) -> StepRegistration | None:
    entry = REGISTRY.get(step_id)
    if entry:
        return entry if isinstance(entry, StepRegistration) else StepRegistration(factory=entry)
    if ":" in step_id:
        mod_name, func_name = step_id.split(":", 1)
        mod = importlib.import_module(mod_name)
        factory = getattr(mod, func_name, None)
        if factory is None:
            raise AttributeError(f"Factory '{func_name}' not found in module '{mod_name}'")
        return StepRegistration(factory=factory)
    return None
