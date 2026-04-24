"""Parse-contract guards for WorkbookIR projection and canonical meta recovery.

These checks keep format-specific parsing on the `WorkbookIR` side of the read
path and ensure generic projection remains backend-neutral and canonical.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

import spreadsheet_handling.io_backends.spreadsheet_contract as sc
import spreadsheet_handling.rendering.workbook_projection as wp
from spreadsheet_handling.io_backends.xlsx.openpyxl_parser import parse_workbook
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
import spreadsheet_handling.io_backends.xlsx.xlsx_backend as xb
from spreadsheet_handling.rendering.ir import WorkbookIR


pytestmark = pytest.mark.ftr("FTR-SPREADSHEET-PARSE-CONTRACT-P3I")


def _path_imports(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def _sample_frames() -> dict[str, object]:
    return {
        "Products": pd.DataFrame(
            [
                {"id": "P-001", "status": "new", "title": "Alpha"},
                {"id": "P-002", "status": "done", "title": "Beta"},
            ]
        ),
        "_meta": {
            "version": "3.2",
            "author": "parse-contract",
            "auto_filter": True,
            "freeze_header": True,
            "helper_prefix": "_",
        },
    }


def test_read_spreadsheet_frames_stops_at_workbook_ir(monkeypatch, tmp_path):
    out = tmp_path / "book.xlsx"
    out.touch()

    sentinel_ir = WorkbookIR()
    calls: list[str] = []
    expected = {"Products": pd.DataFrame({"id": ["P-001"]})}

    def fake_parser(path: str | Path) -> WorkbookIR:
        assert Path(path) == out
        calls.append("parse")
        return sentinel_ir

    def fake_project(ir: WorkbookIR) -> dict[str, object]:
        assert ir is sentinel_ir
        calls.append("project")
        return expected

    monkeypatch.setattr(sc, "workbookir_to_frames", fake_project, raising=True)

    back = sc.read_spreadsheet_frames(out, parser=fake_parser)

    assert back is expected
    assert calls == ["parse", "project"]


def test_excel_backend_read_multi_uses_read_spreadsheet_frames_contract(monkeypatch, tmp_path):
    expected = {"Products": pd.DataFrame({"id": ["P-001"]})}

    def fake_read_frames(path, *, parser):
        assert parser is xb.parse_workbook
        assert Path(path).name == "book.xlsx"
        return expected

    monkeypatch.setattr(xb, "read_spreadsheet_frames", fake_read_frames, raising=True)

    out = tmp_path / "book.xlsx"
    out.touch()

    back = ExcelBackend().read_multi(str(out), header_levels=1)

    assert back is expected


def test_generic_parse_projection_modules_stay_free_of_backend_dependencies():
    forbidden_prefixes = (
        "openpyxl",
        "spreadsheet_handling.io_backends.xlsx",
    )

    for module in (sc, wp):
        imports = _path_imports(Path(module.__file__).resolve())
        violations = [
            name for name in imports
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
        ]
        assert not violations, (
            f"{Path(module.__file__).name} must stay backend-neutral on the generic read path:\n"
            + "\n".join(sorted(violations))
        )


def test_parse_contract_roundtrips_canonical_meta_payload_without_promoting_carrier_hints(tmp_path):
    frames = _sample_frames()
    out = tmp_path / "book.xlsx"

    ExcelBackend().write_multi(frames, str(out))

    ir = parse_workbook(out)
    assert ir.sheets["Products"].meta.get("__autofilter_ref")
    assert ir.sheets["Products"].meta.get("__freeze")
    assert ir.sheets["Products"].meta.get("options") == {
        "auto_filter": True,
        "freeze_header": True,
        "helper_prefix": "_",
    }

    back = sc.read_spreadsheet_frames(out, parser=parse_workbook)

    assert back["_meta"] == frames["_meta"]
    assert "__autofilter_ref" not in back["_meta"]
    assert "__freeze" not in back["_meta"]
    assert "options" not in back["_meta"]
    assert list(back["Products"].columns) == ["id", "status", "title"]
    assert back["Products"].iloc[0]["title"] == "Alpha"
