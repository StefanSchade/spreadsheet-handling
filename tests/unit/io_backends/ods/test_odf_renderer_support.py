from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest

from spreadsheet_handling.io_backends.ods.odf_renderer import render_workbook
from spreadsheet_handling.rendering.plan import (
    ApplyColumnStyle,
    ApplyHeaderStyle,
    DefineSheet,
    MergeCells,
    RenderPlan,
    SetFreeze,
    SetHeader,
    WriteDataBlock,
)


pytestmark = pytest.mark.ftr("FTR-ODS-CALC-ADAPTER-IMPLEMENTATION-P3J")


def _render(plan: RenderPlan, out: Path) -> Path:
    render_workbook(plan, out)
    return out.with_suffix(".ods")


def _xml_root(out: Path, member: str) -> ET.Element:
    with ZipFile(out) as archive:
        return ET.fromstring(archive.read(member))


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _attr(elem: ET.Element, local_name: str) -> str | None:
    for key, value in elem.attrib.items():
        if _local_name(key) == local_name:
            return value
    return None


def test_render_workbook_coalesces_freeze_settings_for_multiple_sheets(tmp_path: Path) -> None:
    plan = RenderPlan()
    plan.add(DefineSheet("Products", 1))
    plan.add(SetHeader("Products", 1, 1, "id"))
    plan.add(SetFreeze("Products", 2, 1))
    plan.add(DefineSheet("Summary", 2))
    plan.add(SetHeader("Summary", 1, 1, "value"))
    plan.add(SetFreeze("Summary", 3, 2))

    out = _render(plan, tmp_path / "freeze.ods")
    root = _xml_root(out, "settings.xml")

    view_settings = [
        elem
        for elem in root.iter()
        if _local_name(elem.tag) == "config-item-set" and _attr(elem, "name") == "ooo:view-settings"
    ]
    sheet_entries = {
        _attr(elem, "name")
        for elem in view_settings[0].iter()
        if _local_name(elem.tag) == "config-item-map-entry" and _attr(elem, "name")
    }

    assert len(view_settings) == 1
    assert {"Products", "Summary"} <= sheet_entries


def test_render_workbook_persists_merged_headers_as_spanned_and_covered_cells(tmp_path: Path) -> None:
    plan = RenderPlan()
    plan.add(DefineSheet("Products", 1))
    plan.add(SetHeader("Products", 1, 1, "Group"))
    plan.add(SetHeader("Products", 2, 1, "id"))
    plan.add(SetHeader("Products", 2, 2, "title"))
    plan.add(MergeCells("Products", 1, 1, 1, 2))

    out = _render(plan, tmp_path / "merge.ods")
    root = _xml_root(out, "content.xml")

    merged_cells = [
        elem
        for elem in root.iter()
        if _local_name(elem.tag) == "table-cell" and _attr(elem, "number-columns-spanned") == "2"
    ]
    covered_cells = [elem for elem in root.iter() if _local_name(elem.tag) == "covered-table-cell"]

    assert merged_cells
    assert covered_cells


def test_render_workbook_persists_header_and_helper_fill_styles(tmp_path: Path) -> None:
    plan = RenderPlan()
    plan.add(DefineSheet("Products", 1))
    plan.add(SetHeader("Products", 1, 1, "id"))
    plan.add(ApplyHeaderStyle("Products", 1, 1, bold=True, fill_rgb="#CCE5FF"))
    plan.add(WriteDataBlock("Products", 2, 1, (("P-001",), ("P-002",))))
    plan.add(ApplyColumnStyle("Products", 1, 2, 3, fill_rgb="#FFF5CC"))

    out = _render(plan, tmp_path / "styles.ods")
    root = _xml_root(out, "content.xml")

    colors = {
        value
        for elem in root.iter()
        for key, value in elem.attrib.items()
        if _local_name(key) == "background-color"
    }
    font_weights = {
        value
        for elem in root.iter()
        for key, value in elem.attrib.items()
        if _local_name(key) == "font-weight"
    }
    styled_cells = [
        elem
        for elem in root.iter()
        if _local_name(elem.tag) == "table-cell" and _attr(elem, "style-name")
    ]

    assert "#CCE5FF" in colors
    assert "#FFF5CC" in colors
    assert "bold" in font_weights
    assert styled_cells
