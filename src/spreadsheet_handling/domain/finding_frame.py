"""Shared domain finding record and finding-frame serialization.

Several domain validations and diagnostic-producing transformations emit a
small finding record and serialize a list of findings to a stable report
DataFrame.  Before this module each producer re-implemented the column list,
the record dataclass, ``to_record``, ``findings_to_frame``, and the
failure-message formatting.  This module owns the genuinely shared mechanics so
the shape, the schema-stable empty frame, and the common failure message are
defined once.

The canonical columns here are the seven-column base shared by
``resource_overrides`` and ``derived_column_policy``.  Producers that need
additional, semantically necessary columns (reference validations carry
``target_frame`` / ``target_columns`` and render ``row_index`` / ``value``
differently) keep their own record dataclass and pass their own column list to
:func:`findings_to_frame`; only the serialization mechanic is shared, not the
record semantics.

This is intentionally *not* the same model as
``domain/validations/findings.py::Finding``.  That one is a
category/severity-policy input consumed by ``apply_severity_policy`` and has no
tabular serialization; collapsing the two would flatten genuinely different
diagnostic semantics.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

# Canonical seven-column finding-frame schema.  Reference validations extend
# this with module-specific ``target_frame`` / ``target_columns`` columns and
# keep their own constant; the shared serialization still drives both.
FINDING_COLUMNS = [
    "rule_type",
    "frame",
    "columns",
    "row_index",
    "value",
    "severity",
    "message",
]


class FindingRecord(Protocol):
    """Anything that can serialize itself to one finding-frame row."""

    def to_record(self) -> dict[str, Any]: ...


def row_index_label(row_index: Any) -> str:
    """Render a row index (a scalar or a tuple of positions) as a label."""
    if isinstance(row_index, tuple):
        return ", ".join(map(str, row_index))
    return str(row_index)


@dataclass(frozen=True)
class Finding:
    """A single finding in the shared seven-column shape."""

    rule_type: str
    frame: str
    columns: list[str]
    row_index: Any
    value: tuple[Any, ...] | None
    severity: str = "warn"
    message: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "rule_type": self.rule_type,
            "frame": self.frame,
            "columns": ", ".join(self.columns),
            "row_index": "" if self.row_index is None else row_index_label(self.row_index),
            "value": "" if self.value is None else " | ".join(map(str, self.value)),
            "severity": self.severity,
            "message": self.message,
        }


def findings_to_frame(
    findings: Iterable[FindingRecord],
    *,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Serialize findings to the stable report frame shape.

    Works for any record exposing ``to_record()``.  ``columns`` defaults to the
    shared seven-column schema; producers with extra columns pass their own
    list.  The empty case still yields a zero-row frame with exactly these
    columns, preserving the schema-stable empty-frame contract.
    """
    if columns is None:
        columns = FINDING_COLUMNS
    return pd.DataFrame(
        [finding.to_record() for finding in findings],
        columns=columns,
    )


def simple_failure_message(findings: Iterable[Finding], *, heading: str) -> str:
    """Format ``heading`` + a flat ``"  - <rule_type>: <message>"`` block.

    This is the shared, uncapped failure shape used by transformations whose
    failure text is a flat list keyed by rule type.  Producers with a
    genuinely distinct failure format (a cap, a configurable name, a per-field
    line) keep their own formatter rather than forcing this one to grow
    options.
    """
    lines = [f"{finding.rule_type}: {finding.message}" for finding in findings]
    return f"{heading}:\n" + "\n".join(f"  - {line}" for line in lines)
