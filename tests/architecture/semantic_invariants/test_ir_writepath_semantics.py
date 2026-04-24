"""Durable semantic invariants for the generic IR write path.

These tests protect the rule that visible spreadsheet behavior is derived from
IR semantics, not from hidden carrier payloads or render-only annotations.
"""
from __future__ import annotations

import copy

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.passes import apply_all as apply_render_passes
from tests.utils.xlsx_normalize import normalize_xlsx


pytestmark = pytest.mark.ftr("FTR-IR-ARCHITECTURE-CLARITY-P3H")


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
        "author": "arch-test",
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


def _visible_shape(shape: dict) -> dict:
    return {
        "sheets": [name for name in shape["sheets"] if name != "_meta"],
        "styles": {name: value for name, value in shape["styles"].items() if name != "_meta"},
        "filters": dict(shape["filters"]),
        "freeze": dict(shape["freeze"]),
        "validations": dict(shape["validations"]),
    }


def test_visible_render_result_is_stable_without_hidden_meta_payload_after_ir_derivation(tmp_path):
    frames = _sample_frames()
    meta = _sample_meta()

    ir = compose_workbook(frames, meta)
    ir = apply_render_passes(ir, meta)

    with_payload = copy.deepcopy(ir)
    without_payload = copy.deepcopy(ir)
    meta_sheet = without_payload.hidden_sheets.get("_meta")
    assert meta_sheet is not None
    assert "workbook_meta_blob" in meta_sheet.meta
    meta_sheet.meta.pop("workbook_meta_blob", None)

    with_path = tmp_path / "with_payload.xlsx"
    without_path = tmp_path / "without_payload.xlsx"

    render_workbook(build_render_plan(with_payload), with_path)
    render_workbook(build_render_plan(without_payload), without_path)

    assert _visible_shape(normalize_xlsx(str(with_path))) == _visible_shape(
        normalize_xlsx(str(without_path))
    )


def test_canonical_meta_roundtrips_without_render_annotations(tmp_path):
    frames = _sample_frames()
    meta = _sample_meta()

    ir = compose_workbook(frames, meta)
    ir = apply_render_passes(ir, meta)

    stripped = copy.deepcopy(ir)
    for sheet in stripped.sheets.values():
        sheet.meta = {key: value for key, value in sheet.meta.items() if not key.startswith("__")}
        sheet.validations = []
        sheet.named_ranges = []

    out = tmp_path / "canonical_payload_only.xlsx"
    render_workbook(build_render_plan(stripped), out)

    back = ExcelBackend().read_multi(str(out), header_levels=1)
    assert back["_meta"] == meta
