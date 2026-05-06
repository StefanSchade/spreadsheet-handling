from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.flow import (
    apply_ir_passes,
    build_render_plan,
    default_p1_passes,
)
from spreadsheet_handling.rendering.plan import SetColumnWidth


pytestmark = pytest.mark.ftr("FTR-COLUMN-WIDTH-ROUNDTRIP-P4")


def test_column_width_metadata_emits_render_ops():
    frames = {"Data": pd.DataFrame({"id": ["P-1"], "title": ["Alpha"]})}
    meta = {
        "sheets": {
            "Data": {
                "column_widths": {
                    "A": {"width": 18.0, "source": "workbook"},
                    "B": {"width": 42.5, "source": "workbook"},
                }
            }
        }
    }
    ir = compose_workbook(frames, meta)
    apply_ir_passes(ir, default_p1_passes())

    plan = build_render_plan(ir)

    width_ops = [op for op in plan.ops if isinstance(op, SetColumnWidth)]
    assert width_ops == [
        SetColumnWidth(sheet="Data", col=1, width=18.0),
        SetColumnWidth(sheet="Data", col=2, width=42.5),
    ]


def test_column_width_metadata_ignores_columns_outside_rendered_extent():
    frames = {"Data": pd.DataFrame({"id": ["P-1"]})}
    meta = {
        "sheets": {
            "Data": {
                "column_widths": {
                    "A": {"width": 18.0, "source": "workbook"},
                    "C": {"width": 42.5, "source": "workbook"},
                }
            }
        }
    }
    ir = compose_workbook(frames, meta)
    apply_ir_passes(ir, default_p1_passes())

    plan = build_render_plan(ir)

    width_ops = [op for op in plan.ops if isinstance(op, SetColumnWidth)]
    assert width_ops == [SetColumnWidth(sheet="Data", col=1, width=18.0)]
