from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.indexing import level0_series
from spreadsheet_handling.pipeline.registry import (
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


def test_add_fk_helpers_rejects_inline_target_policy_conflict() -> None:
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
                    "helper_fields_by_target": {"Products": ["name"]},
                },
            },
        ]
    )

    with pytest.raises(ValueError, match="conflict"):
        run_pipeline(_frames(), steps)


def test_add_fk_helpers_rejects_stale_policy_defaults_outside_allowlist() -> None:
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

    with pytest.raises(ValueError, match="must be included in allowed_helpers"):
        run_pipeline(frames, steps)


def test_add_fk_helpers_rejects_multiple_policy_prefixes() -> None:
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

    with pytest.raises(ValueError, match="multiple helper_prefix"):
        run_pipeline(_frames(), steps)


def test_add_fk_helpers_legacy_inline_behavior_remains_supported() -> None:
    steps = build_steps_from_config(
        [
            {
                "step": "add_fk_helpers",
                "defaults": {
                    "id_field": "code",
                    "helper_fields_by_fk": {"code_(Products)": ["category", "name"]},
                },
            }
        ]
    )

    out = run_pipeline(_frames(), steps)
    lvl0 = [c[0] if isinstance(c, tuple) else c for c in out["Orders"].columns]

    assert lvl0 == [
        "order_id",
        "code_(Products)",
        "_Products_category",
        "_Products_name",
    ]
