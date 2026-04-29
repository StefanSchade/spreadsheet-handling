from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.helper_policies import configure_lookup_helpers


pytestmark = pytest.mark.ftr("FTR-LOOKUP-FK-CONFIGURATION-STEPS-P4")


def _frames() -> dict:
    return {
        "variables": pd.DataFrame(
            {
                "ID": ["v1", "v2"],
                "sort_key": [2, 1],
                "value_label_de": ["Eins", "Zwei"],
                "business_component": ["bc1", "bc2"],
                "active": [True, False],
            }
        )
    }


def test_configure_lookup_helpers_writes_resolved_policy() -> None:
    out = configure_lookup_helpers(
        _frames(),
        lookup="variables",
        key="ID",
        allowed_helpers=["sort_key", "value_label_de", "business_component"],
        default_helpers=["value_label_de"],
        missing="fail",
        order={"helper_position": "before_key", "sort_by": ["sort_key"]},
    )

    policy = out["_meta"]["helper_policies"]["lookup"]["variables"]
    assert policy == {
        "key": "ID",
        "allowed_helpers": ["sort_key", "value_label_de", "business_component"],
        "default_helpers": ["value_label_de"],
        "missing": "fail",
        "order": {"helper_position": "before_key", "sort_by": ["sort_key"]},
    }


def test_configure_lookup_helpers_resolves_auto_allowed_helpers() -> None:
    out = configure_lookup_helpers(
        _frames(),
        lookup="variables",
        key="ID",
        allowed_helpers="auto",
        default_helpers=["value_label_de"],
        auto={
            "helper_candidates": {
                "exclude": ["business_component"],
                "include_if_dtype": ["string", "integer", "boolean"],
            }
        },
    )

    policy = out["_meta"]["helper_policies"]["lookup"]["variables"]
    assert policy["allowed_helpers"] == ["sort_key", "value_label_de", "active"]
    assert policy["default_helpers"] == ["value_label_de"]
    assert policy["key"] == "ID"


def test_configure_lookup_helpers_resolves_auto_default_helpers_from_preference() -> None:
    out = configure_lookup_helpers(
        _frames(),
        lookup="variables",
        key="ID",
        allowed_helpers="auto",
        default_helpers="auto",
        auto={
            "helper_candidates": {
                "exclude": ["business_component"],
                "include_if_dtype": ["string", "integer", "boolean"],
            },
            "default_helpers": {"prefer": ["value_label_de"]},
        },
    )

    policy = out["_meta"]["helper_policies"]["lookup"]["variables"]
    assert policy["allowed_helpers"] == ["sort_key", "value_label_de", "active"]
    assert policy["default_helpers"] == ["value_label_de"]


def test_configure_lookup_helpers_resolves_auto_default_helpers_from_allowlist() -> None:
    out = configure_lookup_helpers(
        _frames(),
        lookup="variables",
        key="ID",
        allowed_helpers=["sort_key", "value_label_de"],
        default_helpers="auto",
    )

    policy = out["_meta"]["helper_policies"]["lookup"]["variables"]
    assert policy["default_helpers"] == ["sort_key"]


def test_configure_lookup_helpers_rejects_defaults_outside_allowlist() -> None:
    with pytest.raises(ValueError, match="must be included in allowed_helpers"):
        configure_lookup_helpers(
            _frames(),
            lookup="variables",
            key="ID",
            allowed_helpers=["sort_key"],
            default_helpers=["value_label_de"],
        )


def test_configure_lookup_helpers_rejects_unknown_helper_columns() -> None:
    with pytest.raises(KeyError, match="not found in lookup frame"):
        configure_lookup_helpers(
            _frames(),
            lookup="variables",
            key="ID",
            allowed_helpers=["sort_key", "missing_column"],
            default_helpers=["sort_key"],
        )
