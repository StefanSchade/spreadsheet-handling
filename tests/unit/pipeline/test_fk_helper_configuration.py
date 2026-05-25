from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.indexing import level0_series
from spreadsheet_handling.pipeline import (
    REGISTRY,
    build_steps_from_config,
    run_pipeline,
)
from spreadsheet_handling.pipeline.types import StepRegistration


pytestmark = pytest.mark.ftr("FTR-FK-HELPER-CONFIGURATION-STEPS-P4")


def _frames() -> dict:
    return {
        "Orders": pd.DataFrame(
            {
                "order_id": ["o1", "o2"],
                "code_(Products)": ["p2", "p1"],
            }
        ),
        "Products": pd.DataFrame(
            {
                "code": ["p1", "p2"],
                "name": ["Alpha", "Beta"],
                "category": ["A", "B"],
            }
        ),
        "Suppliers": pd.DataFrame(
            {
                "code": ["s1", "s2"],
                "name": ["North", "South"],
            }
        ),
    }


def test_configure_fk_helpers_registry_entry() -> None:
    entry = REGISTRY["configure_fk_helpers"]
    assert isinstance(entry, StepRegistration)
    assert entry.target == "spreadsheet_handling.domain.helper_policies:configure_fk_helpers"


def test_add_fk_helpers_uses_resolved_default_policy() -> None:
    steps = build_steps_from_config(
        [
            {
                "step": "configure_fk_helpers",
                "targets": {
                    "Products": {
                        "key": "code",
                        "allowed_helpers": ["name", "category"],
                        "default_helpers": ["category"],
                    }
                },
            },
            {
                "step": "add_fk_helpers",
                "defaults": {"detect_fk": True, "helper_prefix": "_"},
            },
        ]
    )

    out = run_pipeline(_frames(), steps)
    lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["Orders"].columns]

    assert "_Products_category" in lvl0
    assert "_Products_name" not in lvl0
    assert level0_series(out["Orders"], "_Products_category").tolist() == ["B", "A"]


@pytest.mark.ftr("FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5")
def test_add_fk_helpers_ignores_inline_helper_field_overrides() -> None:
    """Inline ``helper_fields_by_target`` is no longer consumed by
    ``add_fk_helpers``: the only relation contract is the v2 policy written
    by ``configure_fk_helpers`` / ``infer_fk_relations``.
    """
    steps = build_steps_from_config(
        [
            {
                "step": "configure_fk_helpers",
                "targets": {
                    "Products": {
                        "key": "code",
                        "allowed_helpers": ["name", "category"],
                        "default_helpers": ["category"],
                    }
                },
            },
            {
                "step": "add_fk_helpers",
                "defaults": {
                    # This v1 hint is intentionally ignored; configured policy
                    # remains authoritative and produces ``_Products_category``.
                    "helper_fields_by_target": {"Products": ["name"]},
                },
            },
        ]
    )

    out = run_pipeline(_frames(), steps)
    lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["Orders"].columns]
    assert "_Products_category" in lvl0
    assert "_Products_name" not in lvl0


@pytest.mark.ftr("FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5")
def test_add_fk_helpers_without_policy_raises_actionable_error() -> None:
    steps = build_steps_from_config([{"step": "add_fk_helpers"}])
    with pytest.raises(ValueError, match="infer_fk_relations"):
        run_pipeline(_frames(), steps)


@pytest.mark.ftr("FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5")
def test_add_fk_helpers_ignores_stale_v1_only_policy() -> None:
    """A v1-only policy without the schema_version 2 marker is no longer
    read by primitives; missing v2 must be reported clearly even when v1 is
    present.
    """
    frames = _frames()
    frames["_meta"] = {
        "helper_policies": {
            "fk": {
                "Products": {
                    "target": "Products",
                    "target_sheet": "Products",
                    "key": "code",
                    "allowed_helpers": ["name"],
                    "default_helpers": ["category"],
                    "helper_prefix": "_",
                    "fk_column": "code_(Products)",
                }
            }
        }
    }
    steps = build_steps_from_config([{"step": "add_fk_helpers"}])
    with pytest.raises(ValueError, match="schema_version: 2"):
        run_pipeline(frames, steps)


@pytest.mark.ftr("FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5")
def test_add_fk_helpers_supports_distinct_helper_prefixes_per_relation() -> None:
    """v2 relations carry per-relation ``helper_prefix``; distinct prefixes
    for different targets coexist in one execution.
    """
    steps = build_steps_from_config(
        [
            {
                "step": "configure_fk_helpers",
                "targets": {
                    "Products": {
                        "key": "code",
                        "allowed_helpers": ["name"],
                        "default_helpers": ["name"],
                        "helper_prefix": "_",
                    },
                    "Suppliers": {
                        "key": "code",
                        "allowed_helpers": ["name"],
                        "default_helpers": ["name"],
                        "helper_prefix": "__",
                    },
                },
            },
            {"step": "add_fk_helpers"},
        ]
    )

    frames = _frames()
    frames["Orders"]["code_(Suppliers)"] = ["s1", "s2"]
    out = run_pipeline(frames, steps)

    lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["Orders"].columns]
    assert "_Products_name" in lvl0
    assert "__Suppliers_name" in lvl0


@pytest.mark.ftr("FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5")
def test_add_fk_helpers_consumes_inferred_relations_path() -> None:
    """``infer_fk_relations`` -> ``add_fk_helpers`` composes through v2 policy."""
    frames = _frames()
    steps = build_steps_from_config(
        [
            {
                "step": "infer_fk_relations",
                "id_columns": ["code"],
                "fk_patterns": ["code_({target})"],
            },
            {"step": "add_fk_helpers"},
        ]
    )

    out = run_pipeline(frames, steps)
    lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["Orders"].columns]
    assert "_Products_name" in lvl0
