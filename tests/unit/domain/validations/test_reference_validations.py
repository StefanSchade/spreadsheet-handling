from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.validations.reference_validations import (
    FINDING_COLUMNS,
    validate_references,
)

pytestmark = pytest.mark.ftr("FTR-STANDARD-REFERENCE-VALIDATIONS-P4A")


def test_primary_key_detects_empty_and_duplicate_values_in_warn_mode() -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {"ID": "v1", "label": "Rate"},
                {"ID": "v1", "label": "Rate duplicate"},
                {"ID": "", "label": "Missing ID"},
            ]
        )
    }

    out = validate_references(
        frames,
        mode="warn",
        findings="reference_findings",
        rules=[{"type": "primary_key", "frame": "variables", "columns": ["ID"]}],
    )

    findings = out["reference_findings"]
    assert list(findings.columns) == FINDING_COLUMNS
    assert findings["rule_type"].tolist() == ["primary_key", "primary_key", "primary_key"]
    assert findings["row_index"].tolist() == [2, 0, 1]
    assert findings["severity"].tolist() == ["warn", "warn", "warn"]
    assert "reference_findings" not in frames


def test_unique_detects_arbitrary_duplicate_columns() -> None:
    frames = {
        "labels": pd.DataFrame(
            [
                {"resource": "rate", "locale": "de", "label": "Rate"},
                {"resource": "rate", "locale": "de", "label": "Annuitaet"},
                {"resource": "rate", "locale": "en", "label": "Rate"},
            ]
        )
    }

    out = validate_references(
        frames,
        rules=[{"type": "unique", "frame": "labels", "columns": ["resource", "locale"]}],
    )

    assert out["validation_findings"].loc[:, ["rule_type", "row_index", "value"]].to_dict(
        orient="records"
    ) == [
        {"rule_type": "unique", "row_index": 0, "value": '["rate", "de"]'},
        {"rule_type": "unique", "row_index": 1, "value": '["rate", "de"]'},
    ]


def test_foreign_key_detects_dangling_references() -> None:
    frames = {
        "variables": pd.DataFrame([{"ID": "v1"}, {"ID": "v2"}]),
        "variable_codes": pd.DataFrame([{"ID": "v1"}, {"ID": "missing"}]),
    }

    out = validate_references(
        frames,
        rules=[
            {
                "type": "foreign_key",
                "frame": "variable_codes",
                "columns": ["ID"],
                "target": "variables",
                "target_columns": ["ID"],
            }
        ],
    )

    assert out["validation_findings"].to_dict(orient="records") == [
        {
            "rule_type": "foreign_key",
            "frame": "variable_codes",
            "columns": "ID",
            "row_index": 1,
            "value": "missing",
            "target_frame": "variables",
            "target_columns": "ID",
            "severity": "warn",
            "message": "Foreign key value is not present in target frame.",
        }
    ]


def test_foreign_key_supports_composite_keys() -> None:
    frames = {
        "variable_products": pd.DataFrame(
            [
                {"variable_id": "v1", "product_id": "p1"},
                {"variable_id": "v2", "product_id": "p2"},
            ]
        ),
        "usage": pd.DataFrame(
            [
                {"variable_id": "v1", "product_id": "p1"},
                {"variable_id": "v1", "product_id": "p2"},
            ]
        ),
    }

    out = validate_references(
        frames,
        rules=[
            {
                "type": "foreign_key",
                "frame": "usage",
                "columns": ["variable_id", "product_id"],
                "target": "variable_products",
                "target_columns": ["variable_id", "product_id"],
            }
        ],
    )

    assert out["validation_findings"].loc[0, "value"] == '["v1", "p2"]'
    assert out["validation_findings"].loc[0, "target_frame"] == "variable_products"


def test_unique_reference_detects_duplicate_tuples() -> None:
    frames = {
        "usage": pd.DataFrame(
            [
                {"variable_id": "v1", "product_id": "p1", "code": "output"},
                {"variable_id": "v1", "product_id": "p1", "code": "input"},
                {"variable_id": "v1", "product_id": "p2", "code": "input"},
            ]
        )
    }

    out = validate_references(
        frames,
        rules=[
            {
                "type": "unique_reference",
                "frame": "usage",
                "columns": ["variable_id", "product_id"],
            }
        ],
    )

    assert out["validation_findings"]["rule_type"].tolist() == [
        "unique_reference",
        "unique_reference",
    ]
    assert out["validation_findings"]["row_index"].tolist() == [0, 1]


def test_fail_mode_raises_from_same_finding_shape() -> None:
    frames = {
        "variables": pd.DataFrame([{"ID": "v1"}]),
        "variable_codes": pd.DataFrame([{"ID": "missing"}]),
    }

    with pytest.raises(ValueError, match="foreign_key variable_codes\\(ID\\).*missing"):
        validate_references(
            frames,
            mode="fail",
            rules=[
                {
                    "type": "foreign_key",
                    "frame": "variable_codes",
                    "columns": ["ID"],
                    "target": "variables",
                    "target_columns": ["ID"],
                }
            ],
        )


def test_successful_warn_mode_writes_empty_findings_frame() -> None:
    frames = {
        "variables": pd.DataFrame([{"ID": "v1"}]),
        "variable_codes": pd.DataFrame([{"ID": "v1"}]),
    }

    out = validate_references(
        frames,
        mode="warn",
        rules=[
            {"type": "primary_key", "frame": "variables", "columns": ["ID"]},
            {
                "type": "foreign_key",
                "frame": "variable_codes",
                "columns": ["ID"],
                "target": "variables",
                "target_columns": ["ID"],
            },
        ],
    )

    assert out["validation_findings"].empty
    assert list(out["validation_findings"].columns) == FINDING_COLUMNS
