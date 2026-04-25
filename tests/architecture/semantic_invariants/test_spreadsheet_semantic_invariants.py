"""Durable spreadsheet-semantics invariants.

These tests aim to protect spreadsheet-neutral contract statements that later
adapters should be able to target without inheriting today's XLSX carrier
shape.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.spreadsheet_contract import read_spreadsheet_frames
from spreadsheet_handling.io_backends.xlsx.openpyxl_parser import parse_workbook
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.formulas import ListLiteralFormulaSpec
from spreadsheet_handling.rendering.passes import apply_all as apply_render_passes
from spreadsheet_handling.rendering.plan import (
    AddValidation,
    DefineNamedRange,
    RenderPlan,
    SetAutoFilter,
    SetFreeze,
    WriteMeta,
)


pytestmark = pytest.mark.ftr("FTR-SPREADSHEET-SEMANTIC-INVARIANTS-P3I")


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
        "version": "3.3",
        "author": "semantic-invariants",
        "freeze_header": True,
        "auto_filter": True,
        "helper_prefix": "_",
        "header_fill_rgb": "#CCE5FF",
        "constraints": [
            {
                "sheet": "Products",
                "column": "status",
                "rule": {"type": "in_list", "values": ["new", "done"]},
            }
        ],
    }


def _semantic_ops(plan: RenderPlan) -> list[tuple]:
    semantic_ops: list[tuple] = []

    for op in plan.ops:
        if isinstance(op, WriteMeta):
            continue
        if isinstance(op, SetFreeze):
            semantic_ops.append(("freeze", op.sheet, op.row, op.col))
        elif isinstance(op, SetAutoFilter):
            semantic_ops.append(("autofilter", op.sheet, op.r1, op.c1, op.r2, op.c2))
        elif isinstance(op, AddValidation):
            semantic_ops.append(
                (
                    "validation",
                    op.sheet,
                    op.kind,
                    op.r1,
                    op.c1,
                    op.r2,
                    op.c2,
                    op.formula,
                )
            )
        elif isinstance(op, DefineNamedRange):
            semantic_ops.append(
                ("named_range", op.name, op.sheet, op.r1, op.c1, op.r2, op.c2)
            )

    return semantic_ops


def test_non_layout_spreadsheet_semantics_reach_backend_neutral_render_plan():
    meta = _sample_meta()
    ir = compose_workbook(_sample_frames(), meta)
    ir = apply_render_passes(ir, meta)
    plan = build_render_plan(ir)

    assert any(isinstance(op, SetFreeze) for op in plan.ops)
    assert any(isinstance(op, SetAutoFilter) for op in plan.ops)
    assert any(isinstance(op, AddValidation) for op in plan.ops)
    assert any(isinstance(op, DefineNamedRange) for op in plan.ops)


@pytest.mark.ftr("FTR-FORMULA-PROVIDERS")
def test_validation_formula_intent_is_structural_not_backend_syntax():
    meta = _sample_meta()
    ir = compose_workbook(_sample_frames(), meta)
    ir = apply_render_passes(ir, meta)

    canonical_rule = ir.hidden_sheets["_meta"].meta["workbook_meta_blob"]["constraints"][0]["rule"]
    assert canonical_rule == {"type": "in_list", "values": ["new", "done"]}

    plan = build_render_plan(ir)
    dv_ops = [op for op in plan.ops if isinstance(op, AddValidation)]

    assert len(dv_ops) == 1
    assert dv_ops[0].formula == ListLiteralFormulaSpec(("new", "done"))


def test_sheet_option_precedence_is_resolved_in_ir_before_adapter_execution():
    meta = {
        "freeze_header": True,
        "auto_filter": True,
        "helper_prefix": "_",
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


def test_roundtrip_restores_canonical_meta_without_promoting_carrier_hints(tmp_path: Path):
    frames = _sample_frames()
    meta = _sample_meta()
    out = tmp_path / "semantic_invariants.xlsx"

    ExcelBackend().write_multi({**frames, "_meta": meta}, str(out))

    ir = parse_workbook(out)
    assert ir.sheets["Products"].meta["options"] == {
        "freeze_header": True,
        "auto_filter": True,
        "helper_prefix": "_",
        "header_fill_rgb": "#CCE5FF",
    }
    assert ir.sheets["Products"].meta["__freeze"] == {"row": 2, "col": 1}
    assert ir.sheets["Products"].meta["__autofilter_ref"]

    back = read_spreadsheet_frames(out, parser=parse_workbook)

    assert back["_meta"] == meta
    assert "__freeze" not in back["_meta"]
    assert "__autofilter_ref" not in back["_meta"]
    assert "options" not in back["_meta"]


def test_hidden_payload_carrier_is_not_authoritative_once_semantics_are_in_ir():
    meta = _sample_meta()
    ir = compose_workbook(_sample_frames(), meta)
    ir = apply_render_passes(ir, meta)

    with_payload = copy.deepcopy(ir)
    without_payload = copy.deepcopy(ir)
    without_payload.hidden_sheets["_meta"].meta.pop("workbook_meta_blob", None)

    assert _semantic_ops(build_render_plan(with_payload)) == _semantic_ops(
        build_render_plan(without_payload)
    )
