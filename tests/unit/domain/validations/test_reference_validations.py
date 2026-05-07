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


@pytest.mark.ftr("FTR-CONDITIONAL-VALIDATION-RULES-P4A")
def test_row_local_when_adds_one_skipped_summary_for_unique_rules() -> None:
    frames = {
        "labels": pd.DataFrame(
            [
                {"resource": "rate", "locale": "de", "active": False},
                {"resource": "rate", "locale": "de", "active": True},
                {"resource": "rate", "locale": "de", "active": True},
            ]
        )
    }

    out = validate_references(
        frames,
        rules=[
            {
                "type": "unique",
                "frame": "labels",
                "columns": ["resource", "locale"],
                "when": {"column": "active", "equals": True},
            }
        ],
    )

    findings = out["validation_findings"]
    assert findings["severity"].tolist() == ["skipped", "warn", "warn"]
    assert findings["severity"].tolist().count("skipped") == 1


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


@pytest.mark.ftr("FTR-CONDITIONAL-VALIDATION-RULES-P4A")
def test_row_local_when_gates_foreign_key_validation_and_reports_skipped_rows() -> None:
    frames = {
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "calculation_targets": pd.DataFrame(
            [
                {"secondary_target_variable_id": "missing_but_disabled", "secondary_target_required": False},
                {"secondary_target_variable_id": "missing_and_enabled", "secondary_target_required": True},
            ]
        ),
    }

    out = validate_references(
        frames,
        rules=[
            {
                "type": "foreign_key",
                "frame": "calculation_targets",
                "columns": ["secondary_target_variable_id"],
                "target": "variables",
                "target_columns": ["variable_id"],
                "when": {"column": "secondary_target_required", "equals": True},
            }
        ],
    )

    assert out["validation_findings"].to_dict(orient="records") == [
        {
            "rule_type": "foreign_key",
            "frame": "calculation_targets",
            "columns": "secondary_target_variable_id",
            "row_index": "",
            "value": "",
            "target_frame": "",
            "target_columns": "",
            "severity": "skipped",
            "message": "Skipped 1 row(s) because when did not match: secondary_target_required equals True.",
        },
        {
            "rule_type": "foreign_key",
            "frame": "calculation_targets",
            "columns": "secondary_target_variable_id",
            "row_index": 1,
            "value": "missing_and_enabled",
            "target_frame": "variables",
            "target_columns": "variable_id",
            "severity": "warn",
            "message": "Foreign key value is not present in target frame.",
        },
    ]


@pytest.mark.ftr("FTR-CONDITIONAL-VALIDATION-RULES-P4A")
def test_enabled_when_disabled_rule_emits_auditable_skipped_summary() -> None:
    frames = {
        "feature_switches": pd.DataFrame([{"key": "operation_routing", "enabled": False}]),
        "optional_operation_routes": pd.DataFrame(
            [
                {"transaction_type_id": "t1", "operation_id": "op1"},
                {"transaction_type_id": "t1", "operation_id": "op1"},
            ]
        ),
    }

    out = validate_references(
        frames,
        rules=[
            {
                "type": "unique_reference",
                "frame": "optional_operation_routes",
                "columns": ["transaction_type_id", "operation_id"],
                "enabled_when": {
                    "frame": "feature_switches",
                    "key": "operation_routing",
                    "column": "enabled",
                    "equals": True,
                },
            }
        ],
    )

    assert out["validation_findings"].to_dict(orient="records") == [
        {
            "rule_type": "unique_reference",
            "frame": "optional_operation_routes",
            "columns": "transaction_type_id, operation_id",
            "row_index": "",
            "value": "",
            "target_frame": "",
            "target_columns": "",
            "severity": "skipped",
            "message": "Validation skipped: enabled_when did not match: enabled equals True.",
        }
    ]


@pytest.mark.ftr("FTR-CONDITIONAL-VALIDATION-RULES-P4A")
def test_enabled_when_active_rule_runs_validation() -> None:
    frames = {
        "feature_switches": pd.DataFrame([{"key": "operation_routing", "enabled": True}]),
        "optional_operation_routes": pd.DataFrame(
            [
                {"transaction_type_id": "t1", "operation_id": "op1"},
                {"transaction_type_id": "t1", "operation_id": "op1"},
            ]
        ),
    }

    out = validate_references(
        frames,
        rules=[
            {
                "type": "unique_reference",
                "frame": "optional_operation_routes",
                "columns": ["transaction_type_id", "operation_id"],
                "enabled_when": {
                    "frame": "feature_switches",
                    "key": "operation_routing",
                    "column": "enabled",
                    "equals": True,
                },
            }
        ],
    )

    assert out["validation_findings"]["severity"].tolist() == ["warn", "warn"]
    assert out["validation_findings"]["rule_type"].tolist() == [
        "unique_reference",
        "unique_reference",
    ]


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


@pytest.mark.ftr("FTR-CONDITIONAL-VALIDATION-RULES-P4A")
def test_row_local_when_adds_one_skipped_summary_for_unique_reference_rules() -> None:
    frames = {
        "usage": pd.DataFrame(
            [
                {"variable_id": "v1", "product_id": "p1", "enabled": False},
                {"variable_id": "v1", "product_id": "p1", "enabled": True},
                {"variable_id": "v1", "product_id": "p1", "enabled": True},
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
                "when": {"column": "enabled", "equals": True},
            }
        ],
    )

    findings = out["validation_findings"]
    assert findings["severity"].tolist() == ["skipped", "warn", "warn"]
    assert findings["severity"].tolist().count("skipped") == 1


def test_unique_reference_can_be_explicitly_disabled_for_template_rules() -> None:
    frames = {
        "usage": pd.DataFrame(
            [
                {"variable_id": "v1", "product_id": "p1"},
                {"variable_id": "v1", "product_id": "p1"},
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
                "allow_duplicates": True,
            }
        ],
    )

    assert out["validation_findings"].empty
    assert list(out["validation_findings"].columns) == FINDING_COLUMNS


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


@pytest.mark.ftr("FTR-CONDITIONAL-VALIDATION-RULES-P4A")
def test_fail_mode_ignores_skipped_rows_but_fails_active_rows() -> None:
    frames = {
        "variables": pd.DataFrame([{"variable_id": "v1"}]),
        "calculation_targets": pd.DataFrame(
            [
                {"secondary_target_variable_id": "missing_but_disabled", "secondary_target_required": False},
                {"secondary_target_variable_id": "missing_and_enabled", "secondary_target_required": True},
            ]
        ),
    }

    with pytest.raises(ValueError, match="missing_and_enabled"):
        validate_references(
            frames,
            mode="fail",
            rules=[
                {
                    "type": "foreign_key",
                    "frame": "calculation_targets",
                    "columns": ["secondary_target_variable_id"],
                    "target": "variables",
                    "target_columns": ["variable_id"],
                    "when": {"column": "secondary_target_required", "equals": True},
                }
            ],
        )


@pytest.mark.ftr("FTR-CONDITIONAL-VALIDATION-RULES-P4A")
def test_disabled_enabled_when_rule_does_not_fail_fail_mode() -> None:
    frames = {
        "feature_switches": pd.DataFrame([{"key": "operation_routing", "enabled": False}]),
        "optional_operation_routes": pd.DataFrame(
            [
                {"transaction_type_id": "t1", "operation_id": "op1"},
                {"transaction_type_id": "t1", "operation_id": "op1"},
            ]
        ),
    }

    out = validate_references(
        frames,
        mode="fail",
        rules=[
            {
                "type": "unique_reference",
                "frame": "optional_operation_routes",
                "columns": ["transaction_type_id", "operation_id"],
                "enabled_when": {
                    "frame": "feature_switches",
                    "key": "operation_routing",
                    "column": "enabled",
                    "equals": True,
                },
            }
        ],
    )

    assert "validation_findings" not in out


def test_ignore_mode_does_not_write_findings_frame_or_raise() -> None:
    frames = {
        "variables": pd.DataFrame([{"ID": "v1"}]),
        "variable_codes": pd.DataFrame([{"ID": "missing"}]),
    }

    out = validate_references(
        frames,
        mode="ignore",
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

    assert "validation_findings" not in out
    assert out["variables"].equals(frames["variables"])


@pytest.mark.ftr("FTR-CONDITIONAL-VALIDATION-RULES-P4A")
def test_missing_switch_configuration_fails_unless_optional() -> None:
    frames = {"variables": pd.DataFrame([{"ID": "v1"}])}
    rule = {
        "type": "primary_key",
        "frame": "variables",
        "columns": ["ID"],
        "enabled_when": {
            "frame": "feature_switches",
            "key": "operation_routing",
            "column": "enabled",
            "equals": True,
        },
    }

    with pytest.raises(KeyError, match="switch frame 'feature_switches' not found"):
        validate_references(frames, rules=[rule])

    out = validate_references(
        frames,
        rules=[{**rule, "enabled_when": {**rule["enabled_when"], "optional": True}}],
    )

    assert out["validation_findings"]["severity"].tolist() == ["skipped"]
    assert "switch frame is missing" in out["validation_findings"].loc[0, "message"]


@pytest.mark.ftr("FTR-CONDITIONAL-VALIDATION-RULES-P4A")
def test_unsupported_condition_predicate_fails_clearly() -> None:
    frames = {"variables": pd.DataFrame([{"ID": "v1", "active": True}])}

    with pytest.raises(ValueError, match="Unsupported when predicate"):
        validate_references(
            frames,
            rules=[
                {
                    "type": "primary_key",
                    "frame": "variables",
                    "columns": ["ID"],
                    "when": {"column": "active", "contains": "yes"},
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
