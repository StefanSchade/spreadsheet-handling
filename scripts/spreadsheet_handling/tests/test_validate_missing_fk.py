# -*- coding: utf-8 -*-
from __future__ import annotations
import pandas as pd
import pytest
from spreadsheet_handling.engine.orchestrator import Engine


def test_missing_fk_warn():
    frames = {
        "A": pd.DataFrame([{"id": 1, "name": "Alpha"}]),
        "B": pd.DataFrame([{"id_(A)": 1}, {"id_(A)": 99}]),
    }
    defaults = {
        "id_field": "id",
        "label_field": "name",
        "helper_prefix": "_",
        "levels": 3,
        "detect_fk": True,
    }
    eng = Engine(defaults)

    # darf NICHT raisen in warn
    report = eng.validate(frames, mode_missing_fk="warn", mode_duplicate_ids="ignore")
    assert "missing_fk" in report and "B" in report["missing_fk"]
    # mindestens ein fehlender Wert 99
    issue_cols = [iss["column"] for iss in report["missing_fk"]["B"]]
    assert "id_(A)" in issue_cols


def test_missing_fk_fail():
    frames = {
        "A": pd.DataFrame([{"id": 1, "name": "Alpha"}]),
        "B": pd.DataFrame([{"id_(A)": 1}, {"id_(A)": 99}]),
    }
    defaults = {
        "id_field": "id",
        "label_field": "name",
        "helper_prefix": "_",
        "levels": 3,
        "detect_fk": True,
    }
    eng = Engine(defaults)

    with pytest.raises(ValueError) as exc:
        eng.validate(frames, mode_missing_fk="fail", mode_duplicate_ids="ignore")
    assert "missing" in str(exc.value).lower()
