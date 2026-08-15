"""Supported public pipeline surface (Trusted Ingress slice E6).

``__all__`` below is the intentional, documented import surface: build steps
with ``build_steps_from_config``/``build_steps_from_yaml`` or the listed
``make_*_step`` factories, execute them with ``run_pipeline`` (step-only,
caller-precondition -- see its own docstring) or reach the framework-managed
macro through ``run_app``/``application.orchestrator.orchestrate`` for
automatic Trusted Ingress establishment. Other module-local factories and
``pipeline.execution_state`` remain internal/importable-only. See
``docs/ai_info/interfaces_and_gates.adoc`` for the full programmatic-surface
contract and ``docs/backlog/FTR-TRUSTED-INGRESS-P4A.adoc`` section 23/46 for
its evidence.
"""

from .config import AppConfig, load_app_config
from .build import build_steps_from_config, build_steps_from_yaml
from .execution import run_pipeline
from .registry import REGISTRY
from .runner import run_app
from .steps import (
    make_apply_fks_step,
    make_apply_overrides_step,
    make_bootstrap_meta_step,
    make_drop_helpers_step,
    make_identity_step,
    make_validate_step,
)
from .types import BoundStep, Step, StepRegistration

__all__ = [
    "BoundStep",
    "Step",
    "StepRegistration",
    "run_pipeline",
    "run_app",
    "build_steps_from_config",
    "build_steps_from_yaml",
    "make_identity_step",
    "make_validate_step",
    "make_apply_fks_step",
    "make_drop_helpers_step",
    "make_bootstrap_meta_step",
    "make_apply_overrides_step",
    "REGISTRY",
    "load_app_config",
    "AppConfig",
]
