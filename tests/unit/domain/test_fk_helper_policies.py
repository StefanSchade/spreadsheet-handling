from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.helper_policies import configure_fk_helpers


pytestmark = pytest.mark.ftr("FTR-FK-HELPER-CONFIGURATION-STEPS-P4")


def _frames() -> dict:
    return {
        "Products": pd.DataFrame(
            {
                "id": ["p1", "p2"],
                "name": ["Alpha", "Beta"],
                "category": ["A", "B"],
                "sort_key": [2, 1],
                "active": [True, False],
            }
        )
    }


def test_configure_fk_helpers_writes_resolved_target_policy() -> None:
    out = configure_fk_helpers(
        _frames(),
        target="Products",
        key="id",
        allowed_helpers=["name", "category"],
        default_helpers=["category"],
        fk_columns={"convention": "{key}_({target})"},
    )

    policy = out["_meta"]["helper_policies"]["fk"]["Products"]
    assert policy == {
        "target": "Products",
        "target_sheet": "Products",
        "key": "id",
        "allowed_helpers": ["name", "category"],
        "default_helpers": ["category"],
        "helper_prefix": "_",
        "fk_column": "id_(Products)",
    }


def test_configure_fk_helpers_resolves_targets_auto() -> None:
    out = configure_fk_helpers(
        _frames(),
        targets="auto",
        auto={
            "id_column_candidates": ["ID", "id"],
            "allowed_helpers": {"exclude": ["sort_key"]},
            "default_helpers": {"prefer": ["name"]},
        },
    )

    policy = out["_meta"]["helper_policies"]["fk"]["Products"]
    assert policy["key"] == "id"
    assert policy["allowed_helpers"] == ["name", "category", "active"]
    assert policy["default_helpers"] == ["name"]
    assert policy["fk_column"] == "id_(Products)"


def test_configure_fk_helpers_accepts_targets_mapping() -> None:
    out = configure_fk_helpers(
        _frames(),
        targets={
            "Products": {
                "key": "id",
                "allowed_helpers": ["name", "category"],
                "default_helpers": ["name"],
            }
        },
    )

    assert out["_meta"]["helper_policies"]["fk"]["Products"]["default_helpers"] == ["name"]


def test_configure_fk_helpers_rejects_defaults_outside_allowlist() -> None:
    with pytest.raises(ValueError, match="must be included in allowed_helpers"):
        configure_fk_helpers(
            _frames(),
            target="Products",
            key="id",
            allowed_helpers=["name"],
            default_helpers=["category"],
        )


def test_configure_fk_helpers_rejects_unknown_target_helper_columns() -> None:
    with pytest.raises(KeyError, match="not found in target frame"):
        configure_fk_helpers(
            _frames(),
            target="Products",
            key="id",
            allowed_helpers=["name", "missing"],
            default_helpers=["name"],
        )
