from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.ods.odf_parser import parse_workbook as parse_ods_workbook
from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.io_backends.xlsx.openpyxl_parser import (
    parse_workbook as parse_xlsx_workbook,
)
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from spreadsheet_handling.rendering.ir import SheetIR


pytestmark = [
    pytest.mark.integ,
    pytest.mark.ftr("FTR-ODS-CALC-PARITY-TESTS-P3J"),
]


def _supported_frames() -> dict[str, object]:
    return {
        "Products": pd.DataFrame(
            [
                {"id": "P-001", "status": "new", "_helper": "A"},
                {"id": "P-002", "status": "done", "_helper": "B"},
            ]
        ),
        "Summary": pd.DataFrame(
            [
                {"metric": "count", "value": "2"},
            ]
        ),
        "_meta": {
            "version": "3.4",
            "author": "cross-adapter-parity",
            "freeze_header": True,
            "auto_filter": True,
            "helper_prefix": "_",
            "header_fill_rgb": "#CCE5FF",
            "helper_fill_rgb": "#FFF5CC",
            "constraints": [
                {
                    "sheet": "Products",
                    "column": "status",
                    "rule": {"type": "in_list", "values": ["new", "done", "archived"]},
                }
            ],
            "sheets": {
                "Summary": {
                    "freeze_header": False,
                }
            },
        },
    }


def _multiheader_frames() -> dict[str, object]:
    columns = pd.MultiIndex.from_tuples(
        [
            ("order", "id"),
            ("order", "status"),
            ("audit", "_helper"),
        ]
    )
    return {
        "Orders": pd.DataFrame(
            [
                ["O-001", "new", "A"],
                ["O-002", "done", "B"],
            ],
            columns=columns,
        ),
        "_meta": {
            "version": "3.4",
            "author": "cross-adapter-parity",
            "freeze_header": True,
            "auto_filter": True,
            "helper_prefix": "_",
        },
    }


def _write_both(frames: dict[str, object], tmp_path: Path, stem: str) -> tuple[Path, Path]:
    xlsx_path = tmp_path / f"{stem}.xlsx"
    ods_path = tmp_path / f"{stem}.ods"

    ExcelBackend().write_multi(frames, str(xlsx_path))
    OdsBackend().write_multi(frames, str(ods_path))

    return xlsx_path, ods_path


def _visible_sheet_names(frames: dict[str, object]) -> list[str]:
    return [
        name
        for name, value in frames.items()
        if name != "_meta" and isinstance(value, pd.DataFrame)
    ]


def _assert_roundtrip_matches_expected(
    actual: dict[str, object],
    expected: dict[str, object],
) -> None:
    expected_visible = _visible_sheet_names(expected)

    assert _visible_sheet_names(actual) == expected_visible
    assert actual["_meta"] == expected["_meta"]

    for name in expected_visible:
        pd.testing.assert_frame_equal(
            actual[name],
            expected[name],
            check_dtype=False,
        )


def _named_range_summary(sheet: SheetIR) -> list[tuple[str, str, tuple[int, int, int, int]]]:
    return sorted(
        (named_range.name, named_range.sheet, named_range.area)
        for named_range in sheet.named_ranges
    )


def _validation_summary(sheet: SheetIR) -> list[tuple[str, tuple[int, int, int, int], str, bool]]:
    return sorted(
        (
            validation.kind,
            validation.area,
            validation.formula,
            validation.allow_empty,
        )
        for validation in sheet.validations
    )


def _supported_sheet_summary(sheet: SheetIR) -> dict[str, Any]:
    table = sheet.tables[0]
    return {
        "headers": list(table.headers),
        "data": [list(row) for row in (table.data or [])],
        "header_rows": table.header_rows,
        "n_rows": table.n_rows,
        "n_cols": table.n_cols,
        "options": dict(sheet.meta.get("options", {})),
        "autofilter_ref": sheet.meta.get("__autofilter_ref"),
        "named_ranges": _named_range_summary(sheet),
        "validations": _validation_summary(sheet),
    }


def _supported_workbook_summary(workbook) -> dict[str, Any]:
    return {
        "visible_sheets": list(workbook.sheets),
        "hidden_sheets": sorted(workbook.hidden_sheets),
        "sheets": {
            name: _supported_sheet_summary(sheet)
            for name, sheet in workbook.sheets.items()
        },
    }


def test_supported_frames_and_meta_roundtrip_portably_across_xlsx_and_ods(tmp_path: Path) -> None:
    frames = _supported_frames()
    xlsx_path, ods_path = _write_both(frames, tmp_path, stem="supported")

    xlsx_back = ExcelBackend().read_multi(str(xlsx_path), header_levels=1)
    ods_back = OdsBackend().read_multi(str(ods_path), header_levels=1)

    _assert_roundtrip_matches_expected(xlsx_back, frames)
    _assert_roundtrip_matches_expected(ods_back, frames)

    for sheet_name in _visible_sheet_names(frames):
        pd.testing.assert_frame_equal(
            xlsx_back[sheet_name],
            ods_back[sheet_name],
            check_dtype=False,
        )
    assert xlsx_back["_meta"] == ods_back["_meta"] == frames["_meta"]


def test_supported_parser_semantics_match_across_xlsx_and_ods(tmp_path: Path) -> None:
    frames = _supported_frames()
    xlsx_path, ods_path = _write_both(frames, tmp_path, stem="semantics")

    xlsx_ir = parse_xlsx_workbook(xlsx_path)
    ods_ir = parse_ods_workbook(ods_path)

    assert _supported_workbook_summary(xlsx_ir) == _supported_workbook_summary(ods_ir)
    assert "_meta" in xlsx_ir.hidden_sheets
    assert "_meta" in ods_ir.hidden_sheets


def test_multiheader_roundtrip_is_portable_across_xlsx_and_ods(tmp_path: Path) -> None:
    frames = _multiheader_frames()
    xlsx_path, ods_path = _write_both(frames, tmp_path, stem="multiheader")

    xlsx_back = ExcelBackend().read_multi(str(xlsx_path), header_levels=1)
    ods_back = OdsBackend().read_multi(str(ods_path), header_levels=1)

    assert isinstance(xlsx_back["Orders"].columns, pd.MultiIndex)
    assert isinstance(ods_back["Orders"].columns, pd.MultiIndex)

    pd.testing.assert_frame_equal(
        xlsx_back["Orders"],
        frames["Orders"],
        check_dtype=False,
    )
    pd.testing.assert_frame_equal(
        ods_back["Orders"],
        frames["Orders"],
        check_dtype=False,
    )
    pd.testing.assert_frame_equal(
        xlsx_back["Orders"],
        ods_back["Orders"],
        check_dtype=False,
    )
    assert xlsx_back["_meta"] == ods_back["_meta"] == frames["_meta"]


def test_freeze_parse_hint_difference_is_an_explicit_accepted_gap(tmp_path: Path) -> None:
    frames = _supported_frames()
    xlsx_path, ods_path = _write_both(frames, tmp_path, stem="freeze-gap")

    xlsx_ir = parse_xlsx_workbook(xlsx_path)
    ods_ir = parse_ods_workbook(ods_path)

    assert xlsx_ir.sheets["Products"].meta["options"]["freeze_header"] is True
    assert ods_ir.sheets["Products"].meta["options"]["freeze_header"] is True

    assert xlsx_ir.sheets["Products"].meta["__freeze"] == {"row": 2, "col": 1}
    assert "__freeze" not in ods_ir.sheets["Products"].meta

    assert "__freeze" not in xlsx_ir.sheets["Summary"].meta
    assert "__freeze" not in ods_ir.sheets["Summary"].meta
