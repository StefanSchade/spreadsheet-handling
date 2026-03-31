"""Backward-compatible facade.

All pipeline types, step factories, and registry have been split into:
  - types.py     — Frames, Step, BoundStep, StepSpec
  - steps.py     — all make_*_step() factories
  - registry.py  — REGISTRY, run_pipeline, build_steps_from_config/yaml

This module re-exports everything so existing imports continue to work.
"""
from __future__ import annotations

# --- types ---
from .types import Frames, Step, BoundStep, StepSpec  # noqa: F401

# --- step factories ---
from .steps import (  # noqa: F401
    make_identity_step,
    make_validate_step,
    make_apply_fks_step,
    make_drop_helpers_step,
    make_flatten_headers_step,
    make_unflatten_headers_step,
    make_reorder_helpers_step,
    make_check_fk_helpers_step,
    make_add_validations_step,
    make_bootstrap_meta_step,
    make_apply_overrides_step,
    make_plugin_step,
)

# --- registry & runner ---
from .registry import (  # noqa: F401
    REGISTRY,
    run_pipeline,
    build_steps_from_config,
    build_steps_from_yaml,
)

