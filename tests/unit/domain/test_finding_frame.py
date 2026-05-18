"""Tests for the shared domain finding record and finding-frame serializer.

Guards the consolidated finding-frame mechanic introduced by
FTR-FINDING-MODEL-CONSOLIDATION-P5: the canonical seven-column schema, the
schema-stable empty frame, the shared record rendering, the custom-column path
used by reference validations, and the shared flat failure message.  Producers
must keep delegating here rather than re-implementing serialization.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from spreadsheet_handling.domain.finding_frame import (
    FINDING_COLUMNS,
    Finding,
    findings_to_frame,
    row_index_label,
    simple_failure_message,
)

pytestmark = pytest.mark.ftr("FTR-FINDING-MODEL-CONSOLIDATION-P5")


def test_canonical_columns_are_the_seven_column_base() -> None:
    assert FINDING_COLUMNS == [
        "rule_type",
        "frame",
        "columns",
        "row_index",
        "value",
        "severity",
        "message",
    ]


def test_row_index_label_renders_scalar_and_tuple() -> None:
    assert row_index_label(5) == "5"
    assert row_index_label((1, 2, 3)) == "1, 2, 3"


def test_to_record_renders_columns_row_index_and_value() -> None:
    finding = Finding(
        rule_type="duplicate_tuple",
        frame="localized_values",
        columns=["resource_key", "locale"],
        row_index=(0, 3),
        value=("a", "b"),
        severity="fail",
        message="Duplicate override tuples must be unique.",
    )

    assert finding.to_record() == {
        "rule_type": "duplicate_tuple",
        "frame": "localized_values",
        "columns": "resource_key, locale",
        "row_index": "0, 3",
        "value": "a | b",
        "severity": "fail",
        "message": "Duplicate override tuples must be unique.",
    }


def test_to_record_empty_row_index_and_value_render_as_blank() -> None:
    record = Finding(
        rule_type="missing_default",
        frame="f",
        columns=["k"],
        row_index=None,
        value=None,
    ).to_record()

    assert record["row_index"] == ""
    assert record["value"] == ""
    assert record["severity"] == "warn"  # shared default
    assert record["message"] == ""


def test_findings_to_frame_uses_canonical_columns_and_rows() -> None:
    frame = findings_to_frame(
        [
            Finding(
                rule_type="missing_default",
                frame="f",
                columns=["k"],
                row_index=None,
                value=("x",),
                severity="warn",
                message="m",
            )
        ]
    )

    assert list(frame.columns) == FINDING_COLUMNS
    assert frame["rule_type"].tolist() == ["missing_default"]
    assert frame["value"].tolist() == ["x"]


def test_empty_findings_to_frame_is_schema_stable() -> None:
    frame = findings_to_frame([])

    assert list(frame.columns) == FINDING_COLUMNS
    assert len(frame) == 0


def test_findings_to_frame_accepts_module_specific_columns() -> None:
    """Any object exposing to_record() serializes against the given columns.

    This is the reference-validations path: a wider, module-specific column
    list with its own record shape, sharing only the serialization mechanic.
    """

    extended_columns = [*FINDING_COLUMNS[:5], "target_frame", *FINDING_COLUMNS[5:]]

    @dataclass(frozen=True)
    class _RefLike:
        def to_record(self) -> dict[str, Any]:
            return {
                "rule_type": "foreign_key",
                "frame": "orders",
                "columns": "customer_id",
                "row_index": 7,  # raw, not labelled — distinct rendering
                "value": "c9",
                "target_frame": "customers",
                "severity": "warn",
                "message": "unresolved",
            }

    frame = findings_to_frame([_RefLike()], columns=extended_columns)

    assert list(frame.columns) == extended_columns
    assert frame["target_frame"].tolist() == ["customers"]
    assert frame["row_index"].tolist() == [7]  # integer preserved, not "7"


def test_empty_findings_to_frame_with_custom_columns_is_schema_stable() -> None:
    columns = [*FINDING_COLUMNS, "target_frame", "target_columns"]
    frame = findings_to_frame([], columns=columns)

    assert list(frame.columns) == columns
    assert len(frame) == 0


def test_simple_failure_message_is_a_flat_uncapped_block() -> None:
    findings = [
        Finding("conflicting_tuple", "f", ["k"], None, None, "fail", "values conflict"),
        Finding("missing_default", "f", ["k"], None, None, "fail", "default missing"),
    ]

    message = simple_failure_message(findings, heading="Resource override normalization failed")

    assert message == (
        "Resource override normalization failed:\n"
        "  - conflicting_tuple: values conflict\n"
        "  - missing_default: default missing"
    )
