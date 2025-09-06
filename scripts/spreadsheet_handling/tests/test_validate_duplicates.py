# -*- coding: utf-8 -*-
from __future__ import annotations
import pandas as pd
import pytest
from spreadsheet_handling.engine.orchestrator import Engine


def test_duplicate_ids_fail():
    frames = {
        "A": pd.DataFrame(
            [{"id": 1, "name": "Alpha"}, {"id": 1, "name": "Beta"}]
        )
    }
    defaults = {"id_field": "id", "label_field": "name", "levels": 3, "detect_fk": True}
    eng = Engine(defaults)

    with pytest.raises(ValueError) as exc:
        eng.validate(frames, mode_missing_fk="ignore", mode_duplicate_ids="fail")

    assert "duplicate" in str(exc.value).lower()

