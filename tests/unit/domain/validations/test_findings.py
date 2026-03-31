"""Tests for the shared Finding / severity-policy machinery."""
from __future__ import annotations

import logging
import pytest

from spreadsheet_handling.domain.validations.findings import (
    Finding,
    apply_severity_policy,
    resolve_severity,
    DEFAULT_POLICY,
)


# ---------------------------------------------------------------------------
# resolve_severity
# ---------------------------------------------------------------------------

class TestResolveSeverity:
    def test_category_match(self):
        f = Finding(category="duplicate_id", sheet="s", column="c")
        policy = {"duplicate_id": "fail", "__default__": "warn"}
        assert resolve_severity(f, policy) == "fail"

    def test_fallback_to_default(self):
        f = Finding(category="unknown_cat", sheet="s", column="c")
        policy = {"duplicate_id": "fail", "__default__": "ignore"}
        assert resolve_severity(f, policy) == "ignore"

    def test_implicit_default_is_warn(self):
        f = Finding(category="anything", sheet="s", column="c")
        assert resolve_severity(f, {}) == "warn"


# ---------------------------------------------------------------------------
# apply_severity_policy
# ---------------------------------------------------------------------------

class TestApplySeverityPolicy:
    def test_ignore_suppresses(self, caplog):
        findings = [Finding(category="dup", sheet="A", column="id", detail="x")]
        policy = {"__default__": "ignore"}
        result = apply_severity_policy(findings, policy)
        assert result is findings
        assert not caplog.records

    def test_warn_logs_warning(self, caplog):
        findings = [Finding(category="dup", sheet="A", column="id", detail="x")]
        policy = {"__default__": "warn"}
        with caplog.at_level(logging.WARNING, logger="sheets.validation"):
            result = apply_severity_policy(findings, policy)
        assert result is findings
        assert any("dup" in r.message for r in caplog.records)

    def test_fail_raises(self):
        findings = [Finding(category="dup", sheet="A", column="id")]
        policy = {"__default__": "fail"}
        with pytest.raises(ValueError, match="Validation failed"):
            apply_severity_policy(findings, policy)

    def test_mixed_policies(self, caplog):
        findings = [
            Finding(category="dup", sheet="A", column="id"),
            Finding(category="missing", sheet="B", column="fk"),
        ]
        policy = {"dup": "ignore", "missing": "warn", "__default__": "fail"}
        with caplog.at_level(logging.WARNING, logger="sheets.validation"):
            apply_severity_policy(findings, policy)
        # "dup" ignored, "missing" warned
        assert any("missing" in r.message for r in caplog.records)
        assert not any("dup" in r.message for r in caplog.records)

    def test_fail_collects_all_failures(self):
        findings = [
            Finding(category="a", sheet="S1", column="c1"),
            Finding(category="b", sheet="S2", column="c2"),
        ]
        policy = {"__default__": "fail"}
        with pytest.raises(ValueError, match="2 finding"):
            apply_severity_policy(findings, policy)

    def test_empty_findings(self):
        result = apply_severity_policy([], {"__default__": "fail"})
        assert result == []

    def test_default_policy_warns(self, caplog):
        findings = [Finding(category="x", sheet="S", column="c")]
        with caplog.at_level(logging.WARNING, logger="sheets.validation"):
            apply_severity_policy(findings, DEFAULT_POLICY)
        assert any("x" in r.message for r in caplog.records)
