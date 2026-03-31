"""Structured validation findings with configurable severity policy.

Validations produce Finding objects; orchestration applies policy.
This keeps validation logic pure and decoupled from control flow.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Sequence

log = logging.getLogger("sheets.validation")

# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------

Severity = Literal["ignore", "warn", "fail"]


@dataclass(frozen=True)
class Finding:
    """A single structured validation finding."""
    category: str       # e.g. "duplicate_id", "unresolvable_fk", "unexpected_helper"
    sheet: str          # sheet name where the finding occurred
    column: str         # relevant column (or "" if sheet-level)
    detail: str = ""    # human-readable description
    severity: Severity = "warn"  # default; overridden by policy


Findings = List[Finding]


# ---------------------------------------------------------------------------
# Severity policy
# ---------------------------------------------------------------------------

# A policy maps category → severity, with a default fallback.
# Example: {"duplicate_id": "fail", "missing_helper": "ignore", "__default__": "warn"}
SeverityPolicy = Dict[str, Severity]

DEFAULT_POLICY: SeverityPolicy = {"__default__": "warn"}


def resolve_severity(finding: Finding, policy: SeverityPolicy) -> Severity:
    """Look up the configured severity for a finding's category."""
    return policy.get(finding.category, policy.get("__default__", "warn"))


def apply_severity_policy(
    findings: Findings,
    policy: SeverityPolicy | None = None,
) -> Findings:
    """
    Apply severity policy to findings: log warnings, raise on failures.

    Returns the findings list unchanged (for chaining / inspection).
    Raises ValueError if any finding resolves to 'fail'.
    """
    pol = policy or DEFAULT_POLICY
    failures: list[str] = []

    for f in findings:
        sev = resolve_severity(f, pol)
        msg = f"[{f.sheet}] {f.category}: {f.column}" + (f" — {f.detail}" if f.detail else "")

        if sev == "fail":
            failures.append(msg)
            log.error(msg)
        elif sev == "warn":
            log.warning(msg)
        # "ignore" → silent

    if failures:
        raise ValueError(
            f"Validation failed ({len(failures)} finding(s)):\n"
            + "\n".join(f"  - {m}" for m in failures)
        )

    return findings
