"""Role-targeted validation fan-out for dynamic workbook-view columns."""

from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import formula_list_values
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution import run_pipeline
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.passes import ValidationPass


pytestmark = pytest.mark.ftr("FTR-DYNAMIC-VIEW-COLUMN-TARGETING-IMPL-P5")


def test_role_targeted_from_legend_validation_fans_out_to_matrix_columns() -> None:
    frames: dict[str, object] = {
        "story_group_matrix_view": pd.DataFrame(
            {
                "story_id": ["s1", "s2"],
                "title": ["Alpha story", "Beta story"],
                "Alpha": ["E", ""],
                "Beta": ["", "S"],
            }
        ),
        "_meta": {
            "xref_crosstable": {
                "story_group_matrix": {
                    "matrix": "story_group_matrix_view",
                    "row_keys": ["story_id"],
                },
            },
            "legend_blocks": {
                "story_group_codes": {
                    "entries": [
                        {"token": "E", "label": "Explicit"},
                        {"token": "S", "label": "Suggested"},
                    ],
                },
            },
        },
    }
    steps = build_steps_from_config(
        [
            {
                "step": "configure_workbook_view",
                "sheets": [
                    {
                        "frame": "story_group_matrix_view",
                        "sheet": "story_group_matrix_view",
                        "helper_columns": ["title"],
                    },
                ],
            },
            {
                "step": "add_validations",
                "rules": [
                    {
                        "target": {
                            "sheet": "story_group_matrix_view",
                            "roles": ["matrix_value"],
                        },
                        "rule": {
                            "type": "from_legend",
                            "legend": "story_group_codes",
                            "include_empty": True,
                        },
                    }
                ],
            },
        ]
    )

    out = run_pipeline(frames, steps)

    constraints = out["_meta"]["constraints"]
    assert [constraint["column"] for constraint in constraints] == ["Alpha", "Beta"]

    ir = compose_workbook(out, out["_meta"])
    ir = ValidationPass().apply(ir)

    validations = ir.sheets["story_group_matrix_view"].validations
    assert [validation.area for validation in validations] == [
        (2, 3, 3, 3),
        (2, 4, 3, 4),
    ]
    assert [formula_list_values(validation.formula) for validation in validations] == [
        ("", "E", "S"),
        ("", "E", "S"),
    ]
