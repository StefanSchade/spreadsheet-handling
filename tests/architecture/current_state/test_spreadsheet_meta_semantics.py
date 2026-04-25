"""Current-state and transitional spreadsheet-meta checks.

This module intentionally keeps smoke/presence checks for transitional
spreadsheet-meta behavior. Durable spreadsheet-semantics invariants live in
``test_spreadsheet_semantic_invariants.py``.
"""

from __future__ import annotations

import ast

import pandas as pd
import pytest

from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.passes import apply_all as apply_render_passes
from spreadsheet_handling.rendering.plan import WriteMeta

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
