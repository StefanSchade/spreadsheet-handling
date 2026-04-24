from __future__ import annotations

import ast
import copy
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
import spreadsheet_handling.io_backends.xlsx.xlsx_backend as xlsx_backend
from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.passes import apply_all as apply_render_passes
from tests.utils.xlsx_normalize import normalize_xlsx

pytestmark = pytest.mark.ftr("FTR-IR-ARCHITECTURE-CLARITY-P3H")

_GENERIC_WRITEPATH_MODULES = [
    "src/spreadsheet_handling/rendering/composer/layout_composer.py",
    "src/spreadsheet_handling/rendering/flow.py",
    "src/spreadsheet_handling/rendering/ir.py",
    "src/spreadsheet_handling/rendering/plan.py",
    "src/spreadsheet_handling/rendering/passes/__init__.py",
    "src/spreadsheet_handling/rendering/passes/core.py",
    "src/spreadsheet_handling/rendering/passes/meta_pass.py",
    "src/spreadsheet_handling/rendering/passes/style_pass.py",
    "src/spreadsheet_handling/rendering/passes/validation_pass.py",
]

_FORBIDDEN_IMPORT_FRAGMENTS = (
    "openpyxl",
    "io_backends.xlsx",
)


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


def test_generic_write_path_modules_do_not_import_xlsx_or_openpyxl():
    root = Path(__file__).resolve().parents[3]
    violations: list[str] = []

    for rel_path in _GENERIC_WRITEPATH_MODULES:
        module_path = root / rel_path
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                targets = [node.module or ""]

            for target in targets:
                if any(fragment in target for fragment in _FORBIDDEN_IMPORT_FRAGMENTS):
                    violations.append(f"{rel_path}: {target}")

    assert not violations, (
        "Generic write-path modules must stay spreadsheet-neutral:\n" + "\n".join(violations)
    )


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

    assert _visible_shape(normalize_xlsx(str(with_path))) == _visible_shape(normalize_xlsx(str(without_path)))


def test_canonical_meta_roundtrips_without_render_annotations(tmp_path):
    frames = _sample_frames()
    meta = _sample_meta()

    ir = compose_workbook(frames, meta)
    ir = apply_render_passes(ir, meta)

    stripped = copy.deepcopy(ir)
    for sh in stripped.sheets.values():
        sh.meta = {key: value for key, value in sh.meta.items() if not key.startswith("__")}
        sh.validations = []
        sh.named_ranges = []

    out = tmp_path / "canonical_payload_only.xlsx"
    render_workbook(build_render_plan(stripped), out)

    back = ExcelBackend().read_multi(str(out), header_levels=1)
    assert back["_meta"] == meta


def test_xlsx_backend_stops_at_render_plan(monkeypatch, tmp_path):
    calls: list[str] = []
    sentinel_plan = object()

    def fake_build_plan(frames, meta):
        calls.append("build_plan")
        return sentinel_plan

    def fake_render(plan, out_path):
        assert plan is sentinel_plan
        calls.append("render")
        Path(out_path).touch()

    monkeypatch.setattr(xlsx_backend, "build_spreadsheet_render_plan", fake_build_plan, raising=True)
    monkeypatch.setattr(xlsx_backend, "render_workbook", fake_render, raising=True)

    out = tmp_path / "book.xlsx"
    ExcelBackend().write_multi(_sample_frames(), out)

    assert calls == ["build_plan", "render"]
    assert out.exists()
