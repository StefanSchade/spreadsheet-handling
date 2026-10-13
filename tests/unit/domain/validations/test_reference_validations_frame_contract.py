"""``validate_references`` rules ``required_columns`` and ``non_empty``.

Consumer-neutral contract checks over frames: a frame carries its declared columns
(optionally exactly those, in any order) and its cells hold values.
"""

from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.validations.reference_validations import validate_references
from spreadsheet_handling.pipeline.config import load_app_config
from spreadsheet_handling.pipeline.runner import run_app

pytestmark = pytest.mark.ftr("FTR-STANDARD-REFERENCE-VALIDATIONS-P4A")


def _findings(frames, *rules):
    out = validate_references(frames, rules=list(rules))
    return out["validation_findings"].to_dict(orient="records")


def test_required_columns_pass_when_present_in_any_order_with_extras_allowed() -> None:
    frames = {"t": pd.DataFrame([{"b": "1", "a": "2", "extra": "3"}])}

    assert _findings(frames, {"type": "required_columns", "frame": "t", "columns": ["a", "b"]}) == []


def test_required_columns_report_missing_columns() -> None:
    frames = {"t": pd.DataFrame([{"a": "1"}])}

    [finding] = _findings(
        frames, {"type": "required_columns", "frame": "t", "columns": ["a", "b", "c"]}
    )

    assert finding["rule_type"] == "required_columns"
    assert finding["frame"] == "t"
    assert "missing" in finding["message"]
    assert "'b'" in finding["message"] and "'c'" in finding["message"]


def test_required_columns_report_a_missing_frame() -> None:
    [finding] = _findings(
        {"other": pd.DataFrame()},
        {"type": "required_columns", "frame": "t", "columns": ["a"]},
    )

    assert finding["frame"] == "t"
    assert "missing" in finding["message"]


def test_exact_required_columns_reject_unexpected_columns_but_not_order() -> None:
    rule = {"type": "required_columns", "frame": "t", "columns": ["a", "b"], "exact": True}

    assert _findings({"t": pd.DataFrame([{"b": "1", "a": "2"}])}, rule) == []

    [finding] = _findings({"t": pd.DataFrame([{"a": "1", "b": "2", "stray": "3"}])}, rule)
    assert finding["columns"] == "stray"
    assert "Unexpected" in finding["message"]


def test_required_columns_exact_must_be_boolean() -> None:
    with pytest.raises(TypeError, match="exact"):
        validate_references(
            {"t": pd.DataFrame([{"a": "1"}])},
            rules=[{"type": "required_columns", "frame": "t", "columns": ["a"], "exact": "yes"}],
        )


def test_non_empty_accepts_filled_cells() -> None:
    frames = {"t": pd.DataFrame([{"a": "x", "b": 0}, {"a": "y", "b": False}])}

    assert _findings(frames, {"type": "non_empty", "frame": "t", "columns": ["a", "b"]}) == []


def test_non_empty_reports_each_empty_cell_with_row_and_column() -> None:
    frames = {"t": pd.DataFrame([{"a": "x", "b": ""}, {"a": None, "b": "y"}, {"a": "z", "b": "w"}])}

    findings = _findings(frames, {"type": "non_empty", "frame": "t", "columns": ["a", "b"]})

    assert [(f["columns"], f["row_index"]) for f in findings] == [("a", 1), ("b", 0)]
    assert {f["rule_type"] for f in findings} == {"non_empty"}


def test_non_empty_treats_a_cell_missing_from_some_rows_as_empty() -> None:
    frames = {"t": pd.DataFrame([{"a": "x", "b": "y"}, {"a": "z"}])}

    findings = _findings(frames, {"type": "non_empty", "frame": "t", "columns": ["b"]})

    assert [(f["columns"], f["row_index"]) for f in findings] == [("b", 1)]


def test_non_empty_trimmed_rejects_surrounding_whitespace_only_when_asked() -> None:
    frames = {"t": pd.DataFrame([{"a": "x "}, {"a": " y"}, {"a": "z z"}, {"a": 7}])}
    plain = {"type": "non_empty", "frame": "t", "columns": ["a"]}

    assert _findings(frames, plain) == []

    findings = _findings(frames, {**plain, "trimmed": True})
    assert [f["row_index"] for f in findings] == [0, 1]
    assert all("whitespace" in f["message"] for f in findings)


def test_non_empty_trimmed_must_be_boolean() -> None:
    with pytest.raises(TypeError, match="trimmed"):
        validate_references(
            {"t": pd.DataFrame([{"a": "x"}])},
            rules=[{"type": "non_empty", "frame": "t", "columns": ["a"], "trimmed": 1}],
        )


def test_non_empty_reports_missing_column_instead_of_raising() -> None:
    [finding] = _findings(
        {"t": pd.DataFrame([{"a": "x"}])},
        {"type": "non_empty", "frame": "t", "columns": ["nope"]},
    )

    assert "missing" in finding["message"]


def test_non_empty_honours_row_local_when() -> None:
    frames = {"t": pd.DataFrame([{"on": True, "a": ""}, {"on": False, "a": ""}])}

    findings = _findings(
        frames,
        {
            "type": "non_empty",
            "frame": "t",
            "columns": ["a"],
            "when": {"column": "on", "equals": True},
        },
    )

    assert [f["severity"] for f in findings] == ["skipped", "warn"]
    assert findings[1]["row_index"] == 0


def test_fail_mode_raises_for_the_new_rules() -> None:
    frames = {"t": pd.DataFrame([{"a": ""}])}

    with pytest.raises(ValueError, match="non_empty t\\(a\\) row 0"):
        validate_references(
            frames, mode="fail", rules=[{"type": "non_empty", "frame": "t", "columns": ["a"]}]
        )


def test_contract_rules_run_from_a_pipeline_configuration(tmp_path) -> None:
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "t.json").write_text('[{"a": "x", "b": ""}]', encoding="utf-8")
    config = tmp_path / "pipeline.yaml"
    config.write_text(
        f"""
io:
  inputs:
    primary: {{kind: json_dir, path: {in_dir}}}
  output: {{kind: discard, path: {tmp_path / "unused"}}}
pipeline:
  - step: validate_references
    mode: fail
    rules:
      - {{type: required_columns, frame: t, columns: [a, b], exact: true}}
      - {{type: non_empty, frame: t, columns: [a, b]}}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"non_empty t\(b\) row 0"):
        run_app(load_app_config(str(config)), run_id="contract")
