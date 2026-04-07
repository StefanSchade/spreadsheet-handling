from __future__ import annotations

import ast

import pandas as pd
import pytest

from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.passes import apply_all as apply_render_passes
from spreadsheet_handling.rendering.plan import (
    AddValidation,
    DefineNamedRange,
    SetAutoFilter,
    SetFreeze,
    WriteMeta,
)

pytestmark = pytest.mark.ftr("FTR-SPREADSHEET-META-SEMANTICS-P3H")


def _sample_frames() -> dict[str, pd.DataFrame]:
    return {
        "Products": pd.DataFrame(
            [
                {"id": "P-1", "status": "new", "title": "Alpha"},
                {"id": "P-2", "status": "done", "title": "Beta"},
            ]
        )
    }


def _sample_meta() -> dict:
    return {
        "version": "3.1",
        "author": "meta-semantics",
        "freeze_header": True,
        "auto_filter": True,
        "header_fill_rgb": "#CCE5FF",
        "constraints": [
            {
                "sheet": "Products",
                "column": "status",
                "rule": {"type": "in_list", "values": ["new", "done"]},
            }
        ],
    }


def test_current_hidden_meta_payload_carrier_is_reconstructible():
    # Current-carrier smoke test: the hidden workbook payload remains
    # reconstructible from the WriteMeta op emitted by today's write path.
    meta = _sample_meta()
    ir = compose_workbook(_sample_frames(), meta)
    ir = apply_render_passes(ir, meta)
    plan = build_render_plan(ir)

    meta_ops = [op for op in plan.ops if isinstance(op, WriteMeta)]

    assert len(meta_ops) == 1
    assert meta_ops[0].sheet == "_meta"
    assert meta_ops[0].hidden is True
    assert ast.literal_eval(meta_ops[0].kv["workbook_meta_blob"]) == meta


def test_non_layout_spreadsheet_semantics_reach_render_plan():
    meta = _sample_meta()
    ir = compose_workbook(_sample_frames(), meta)
    ir = apply_render_passes(ir, meta)
    plan = build_render_plan(ir)

    assert any(isinstance(op, SetFreeze) for op in plan.ops)
    assert any(isinstance(op, SetAutoFilter) for op in plan.ops)
    assert any(isinstance(op, AddValidation) for op in plan.ops)
    assert any(isinstance(op, DefineNamedRange) for op in plan.ops)


def test_sheet_options_override_workbook_defaults_before_render_plan():
    meta = {
        "freeze_header": True,
        "auto_filter": True,
        "sheets": {
            "Products": {
                "freeze_header": False,
            }
        },
    }
    ir = compose_workbook(_sample_frames(), meta)

    assert ir.sheets["Products"].meta["options"]["auto_filter"] is True
    assert ir.sheets["Products"].meta["options"]["freeze_header"] is False

    ir = apply_render_passes(ir, meta)
    plan = build_render_plan(ir)

    assert any(isinstance(op, SetAutoFilter) for op in plan.ops)
    assert not any(isinstance(op, SetFreeze) for op in plan.ops)


def test_validation_formula_is_derived_adapter_expression_not_canonical_rule():
    meta = _sample_meta()
    ir = compose_workbook(_sample_frames(), meta)
    ir = apply_render_passes(ir, meta)

    canonical_rule = ir.hidden_sheets["_meta"].meta["workbook_meta_blob"]["constraints"][0]["rule"]
    assert canonical_rule == {"type": "in_list", "values": ["new", "done"]}

    plan = build_render_plan(ir)
    dv_ops = [op for op in plan.ops if isinstance(op, AddValidation)]

    assert len(dv_ops) == 1
    assert dv_ops[0].formula == '"new,done"'
