from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from spreadsheet_handling.io_backends.ods.odf_parser import parse_workbook


pytestmark = pytest.mark.ftr("FTR-ODS-PARSER-ROBUSTNESS-P3K")


_ODS_MIMETYPE = "application/vnd.oasis.opendocument.spreadsheet"

_CONTENT_XML_TEMPLATE = """<?xml version='1.0' encoding='UTF-8'?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" office:version="1.2"><office:automatic-styles/><office:body><office:spreadsheet>{spreadsheet_inner}</office:spreadsheet></office:body></office:document-content>
"""

_STYLES_XML_TEMPLATE = """<?xml version='1.0' encoding='UTF-8'?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" office:version="1.2"><office:styles>{styles_body}</office:styles><office:automatic-styles/></office:document-styles>
"""

_META_XML = """<?xml version='1.0' encoding='UTF-8'?>
<office:document-meta
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
    xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
    xmlns:chart="urn:oasis:names:tc:opendocument:xmlns:chart:1.0"
    xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
    xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    office:version="1.2">
  <office:meta>
    <meta:generator>manual-test-fixture</meta:generator>
  </office:meta>
</office:document-meta>
"""

_MANIFEST_XML = """<?xml version='1.0' encoding='UTF-8'?>
<manifest:manifest
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
    xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
    xmlns:chart="urn:oasis:names:tc:opendocument:xmlns:chart:1.0"
    xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
    xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
  <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>
  <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""


def _write_manual_ods_fixture(
    tmp_path: Path,
    name: str,
    *,
    spreadsheet_inner: str,
    styles_body: str = "",
) -> Path:
    """Build a tiny ODS package without using the project's write path."""
    out = tmp_path / name
    content_xml = _CONTENT_XML_TEMPLATE.format(spreadsheet_inner=spreadsheet_inner)
    styles_xml = _STYLES_XML_TEMPLATE.format(styles_body=styles_body)

    with ZipFile(out, "w") as archive:
        archive.writestr("mimetype", _ODS_MIMETYPE, compress_type=ZIP_STORED)
        archive.writestr("content.xml", content_xml, compress_type=ZIP_DEFLATED)
        archive.writestr("styles.xml", styles_xml, compress_type=ZIP_DEFLATED)
        archive.writestr("meta.xml", _META_XML, compress_type=ZIP_DEFLATED)
        archive.writestr("META-INF/manifest.xml", _MANIFEST_XML, compress_type=ZIP_DEFLATED)

    return out


def test_parse_workbook_handles_empty_spreadsheet_package(tmp_path: Path) -> None:
    out = _write_manual_ods_fixture(tmp_path, "empty_workbook.ods", spreadsheet_inner="")

    ir = parse_workbook(out)

    assert ir.sheets == {}
    assert ir.hidden_sheets == {}


def test_parse_workbook_handles_table_without_rows_with_empty_fallback(tmp_path: Path) -> None:
    out = _write_manual_ods_fixture(
        tmp_path,
        "table_without_rows.ods",
        spreadsheet_inner='<table:table table:name="EmptySheet"></table:table>',
    )

    ir = parse_workbook(out)

    sheet = ir.sheets["EmptySheet"]
    table = sheet.tables[0]
    assert table.headers == [""]
    assert table.data == []
    assert table.n_rows == 1
    assert table.n_cols == 1


def test_parse_workbook_handles_manual_text_only_fixture_outside_project_writer(
    tmp_path: Path,
) -> None:
    out = _write_manual_ods_fixture(
        tmp_path,
        "manual_text_only.ods",
        spreadsheet_inner=(
            '<table:table table:name="Manual">'
            "<table:table-row>"
            "<table:table-cell><text:p>manual-value</text:p></table:table-cell>"
            "</table:table-row>"
            "</table:table>"
        ),
    )

    ir = parse_workbook(out)

    sheet = ir.sheets["Manual"]
    table = sheet.tables[0]
    assert table.headers == ["manual-value"]
    assert table.data == []
    assert table.n_rows == 1


def test_parse_workbook_ignores_missing_validation_definitions_and_invalid_filter_ranges(
    tmp_path: Path,
) -> None:
    out = _write_manual_ods_fixture(
        tmp_path,
        "missing_validation_and_bad_filter.ods",
        spreadsheet_inner=(
            "<table:database-ranges>"
            '<table:database-range table:name="bad_filter" table:target-range-address="not-a-range"/>'
            "</table:database-ranges>"
            '<table:table table:name="Products">'
            "<table:table-row>"
            "<table:table-cell><text:p>status</text:p></table:table-cell>"
            "</table:table-row>"
            "<table:table-row>"
            '<table:table-cell table:content-validation-name="missing_rule">'
            "<text:p>new</text:p>"
            "</table:table-cell>"
            "</table:table-row>"
            "</table:table>"
        ),
    )

    ir = parse_workbook(out)

    sheet = ir.sheets["Products"]
    assert sheet.validations == []
    assert "__autofilter_ref" not in sheet.meta
    assert sheet.tables[0].data == [["new"]]


def test_parse_workbook_ignores_invalid_named_range_addresses(tmp_path: Path) -> None:
    out = _write_manual_ods_fixture(
        tmp_path,
        "invalid_named_range.ods",
        spreadsheet_inner=(
            '<table:table table:name="Products">'
            "<table:named-expressions>"
            '<table:named-range table:name="bad_range" table:cell-range-address="not-a-range"/>'
            "</table:named-expressions>"
            "<table:table-row>"
            "<table:table-cell><text:p>id</text:p></table:table-cell>"
            "</table:table-row>"
            "<table:table-row>"
            "<table:table-cell><text:p>P-001</text:p></table:table-cell>"
            "</table:table-row>"
            "</table:table>"
        ),
    )

    ir = parse_workbook(out)

    sheet = ir.sheets["Products"]
    assert sheet.named_ranges == []
    assert sheet.tables[0].data == [["P-001"]]


def test_parse_workbook_handles_workbook_with_only_hidden_tables(tmp_path: Path) -> None:
    out = _write_manual_ods_fixture(
        tmp_path,
        "hidden_only.ods",
        spreadsheet_inner=(
            '<table:table table:name="HiddenData" table:style-name="hidden_table_style">'
            "<table:table-row>"
            "<table:table-cell><text:p>secret</text:p></table:table-cell>"
            "</table:table-row>"
            "</table:table>"
        ),
        styles_body=(
            '<style:style style:name="hidden_table_style" style:family="table">'
            '<style:table-properties table:display="false"/>'
            "</style:style>"
        ),
    )

    ir = parse_workbook(out)

    assert ir.sheets == {}
    assert "HiddenData" in ir.hidden_sheets
    assert ir.hidden_sheets["HiddenData"].meta["_hidden"] is True
