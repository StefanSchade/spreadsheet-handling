"""Main FK helper enrichment orchestration and public enrichment entry point.

Behavior-preserving split out of the former single ``fk_helpers`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-FK-HELPERS-P5).
"""
from __future__ import annotations

from typing import Any

from ....core.fk import (
    build_registry,
    build_id_value_maps,
    detect_fk_columns,
    apply_fk_helpers as _apply_fk_helpers,
)
from ....frame_keys import copy_reserved_frames, iter_data_frames

from .formula_provider import _lookup_formula_provider
from .policy import _defaults_with_fk_policies, _validate_fk_policy_usage
from .provenance import _write_helper_provenance

Frames = dict[str, Any]

_VALUE_HELPER_MODES = {"value", "values"}
_FORMULA_HELPER_MODES = {"formula", "formulas"}


def enrich_helpers(frames: Frames, defaults: dict[str, Any]) -> Frames:
    """Detect FK columns, add helper columns, and write derived provenance.

    This is the domain entry-point called by the ``apply_fks`` pipeline step.
    It orchestrates core.fk utilities and owns the ``_meta`` provenance
    contract for helper columns.
    """
    if not bool(defaults.get("detect_fk", True)):
        return frames

    execution_defaults, fk_policies = _defaults_with_fk_policies(frames, defaults)

    reg = build_registry(frames, execution_defaults)
    levels = int(execution_defaults.get("levels", 3))
    helper_prefix = str(execution_defaults.get("helper_prefix", "_"))
    helper_value_mode = _helper_value_mode(execution_defaults)
    helper_value_provider = (
        _lookup_formula_provider(reg)
        if helper_value_mode in _FORMULA_HELPER_MODES
        else None
    )
    fk_defs_by_sheet: dict[str, Any] = {}
    fields_by_target: dict[str, list[str]] = {}

    for sheet_name, df in iter_data_frames(frames):
        fk_defs = detect_fk_columns(
            df,
            reg,
            helper_prefix=helper_prefix,
            defaults=execution_defaults,
        )
        fk_defs_by_sheet[sheet_name] = fk_defs
        for fk in fk_defs:
            fields_by_target.setdefault(fk.target_sheet_key, [])
            if fk.value_field not in fields_by_target[fk.target_sheet_key]:
                fields_by_target[fk.target_sheet_key].append(fk.value_field)

    _validate_fk_policy_usage(fk_defs_by_sheet, fk_policies)

    id_maps = build_id_value_maps(frames, reg, fields_by_sheet=fields_by_target)

    out: dict[str, Any] = {}
    copy_reserved_frames(frames, out)
    for sheet_name, df in iter_data_frames(frames):
        fk_defs = fk_defs_by_sheet[sheet_name]
        out[sheet_name] = _apply_fk_helpers(
            df,
            fk_defs,
            id_maps,
            levels,
            helper_prefix=helper_prefix,
            helper_value_provider=helper_value_provider,
        )

    _write_helper_provenance(out, fk_defs_by_sheet)
    return out


def _helper_value_mode(defaults: dict[str, Any]) -> str:
    mode = str(defaults.get("helper_value_mode", "values")).lower()
    if mode not in _VALUE_HELPER_MODES and mode not in _FORMULA_HELPER_MODES:
        raise ValueError(
            "helper_value_mode must be one of "
            f"{sorted(_VALUE_HELPER_MODES | _FORMULA_HELPER_MODES)}"
        )
    return mode
