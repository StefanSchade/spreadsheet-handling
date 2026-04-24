"""Spreadsheet-contract guards for the XLSX backend handoff boundary.

These tests verify that the backend stays on the generic spreadsheet contract
facade for read and write orchestration and stops at backend-neutral
RenderPlan execution.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
import spreadsheet_handling.io_backends.xlsx.xlsx_backend as xb

pytestmark = pytest.mark.ftr('FTR-SPREADSHEET-BACKEND-CONTRACT-P3H')


def test_xlsx_backend_uses_spreadsheet_contract_for_write(monkeypatch, tmp_path):
    calls: list[str] = []
    sentinel_plan = object()

    def fake_build_plan(frames, meta):
        assert 'Sheet1' in frames
        calls.append('build_plan')
        return sentinel_plan

    def fake_render(plan, out_path):
        assert plan is sentinel_plan
        calls.append('render')
        Path(out_path).touch()

    monkeypatch.setattr(xb, 'build_spreadsheet_render_plan', fake_build_plan, raising=True)
    monkeypatch.setattr(xb, 'render_workbook', fake_render, raising=True)

    frames = {'Sheet1': pd.DataFrame({'a': [1, 2]})}
    out = tmp_path / 'book.xlsx'

    ExcelBackend().write_multi(frames, out)

    assert calls == ['build_plan', 'render']
    assert out.exists()


def test_xlsx_backend_uses_spreadsheet_contract_for_read(monkeypatch, tmp_path):
    expected = {'Sheet1': pd.DataFrame({'a': [1, 2]})}

    def fake_read_frames(path, *, parser):
        assert parser is xb.parse_workbook
        assert Path(path).name == 'book.xlsx'
        return expected

    monkeypatch.setattr(xb, 'read_spreadsheet_frames', fake_read_frames, raising=True)

    out = tmp_path / 'book.xlsx'
    out.touch()

    back = ExcelBackend().read_multi(str(out), header_levels=1)

    assert back is expected


def test_xlsx_backend_imports_spreadsheet_contract_not_rendering_internals():
    module_path = Path(xb.__file__).resolve()
    tree = ast.parse(module_path.read_text(encoding='utf-8'), filename=str(module_path))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or '')

    forbidden = (
        'spreadsheet_handling.rendering.composer',
        'spreadsheet_handling.rendering.passes',
        'spreadsheet_handling.rendering.flow',
        'spreadsheet_handling.rendering.parse_ir',
    )
    violations = [name for name in imports if any(name.startswith(prefix) for prefix in forbidden)]

    assert not violations, (
        'xlsx_backend.py must depend on the spreadsheet contract instead of rendering internals:\n'
        + '\n'.join(sorted(violations))
    )
    assert 'spreadsheet_handling.io_backends.spreadsheet_contract' in imports


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

    monkeypatch.setattr(xb, "build_spreadsheet_render_plan", fake_build_plan, raising=True)
    monkeypatch.setattr(xb, "render_workbook", fake_render, raising=True)

    out = tmp_path / "book.xlsx"
    ExcelBackend().write_multi({"Sheet1": pd.DataFrame({"a": [1, 2]})}, out)

    assert calls == ["build_plan", "render"]
    assert out.exists()
