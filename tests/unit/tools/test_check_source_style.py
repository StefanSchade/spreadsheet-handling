"""Unit coverage for the repository-local source-style guard tool."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = REPO_ROOT / "tools" / "check_source_style.py"

spec = importlib.util.spec_from_file_location("check_source_style", TOOL_PATH)
assert spec is not None
check_source_style = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = check_source_style
spec.loader.exec_module(check_source_style)

pytestmark = pytest.mark.ftr("FTR-SOURCE-STYLE-GUARDRAILS-P4")


def test_nested_conditional_expression_is_an_error(tmp_path: Path) -> None:
    module_path = tmp_path / "src" / "spreadsheet_handling" / "example.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "def choose(value: int) -> str:",
                "    return 'a' if value == 1 else ('b' if value == 2 else 'c')",
            ]
        ),
        encoding="utf-8",
    )

    findings = check_source_style.collect_findings(tmp_path, ["src/spreadsheet_handling"])

    assert any(
        finding.rule == "nested-conditional-expression" and finding.severity == "ERROR"
        for finding in findings
    )


def test_allowlist_suppresses_matching_function_length_finding() -> None:
    finding = check_source_style.Finding(
        rule="function-length",
        severity="WARN",
        path="src/spreadsheet_handling/example.py",
        line=10,
        symbol="long_function",
        message="too long",
    )
    allowlist_entry = check_source_style.AllowlistEntry(
        rule="function-length",
        path="src/spreadsheet_handling/example.py",
        symbol="long_function",
        line=None,
        rationale="fixture",
        owner="test",
        review_date="2026-05-06",
    )

    active, allowed = check_source_style.apply_allowlist([finding], [allowlist_entry])

    assert active == []
    assert allowed == [finding]


def test_german_comment_is_error_but_localized_test_data_is_accepted(tmp_path: Path) -> None:
    module_path = tmp_path / "tests" / "unit" / "example_test.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "def test_localized_fixture_data() -> None:",
                "    data = {'straße': 'T-Rex-Weg'}",
                "    assert data['straße']",
                "",
                "# nicht wieder einfuehren",
            ]
        ),
        encoding="utf-8",
    )

    findings = check_source_style.collect_findings(tmp_path, ["tests/unit"])

    assert [finding.rule for finding in findings] == ["german-source-comment"]
    assert findings[0].severity == "ERROR"
