"""Regression tests for BUG-ODS-REIMPORT-REPEATED-CELL-MEMORY-EXPLOSION.

LibreOffice writes ``number-columns-repeated`` / ``number-rows-repeated`` on
empty cells that carry sheet-wide formatting (e.g. after a Ctrl+A + style
change). A naive parser materializes every implied cell into memory, which on
real-world inputs translates to billions of dict entries and OOM crashes.

These tests synthesize the carrier pattern via a minimal ODS package (no Dino
fixture, no consumer data) and verify:

* empty repeated columns / rows are not materialized,
* non-empty repeated cells stay intact (the parser still respects them),
* configured ``ParserLimits`` raise ``SpreadsheetTooLargeError`` before
  unbounded allocation when an input declares implausible dimensions.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from spreadsheet_handling.io_backends.ods.odf_parser import (
    _parse_table_grid,
    parse_workbook,
)
from spreadsheet_handling.io_backends.parser_limits import (
    ParserLimits,
    SpreadsheetTooLargeError,
)

pytestmark = pytest.mark.ftr("BUG-ODS-REIMPORT-REPEATED-CELL-MEMORY-EXPLOSION")


_ODS_MIMETYPE = "application/vnd.oasis.opendocument.spreadsheet"

_CONTENT_XML_TEMPLATE = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    "<office:document-content "
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'office:version="1.2">'
    "<office:automatic-styles/>"
    "<office:body><office:spreadsheet>{spreadsheet_inner}</office:spreadsheet></office:body>"
    "</office:document-content>"
)

_STYLES_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    "<office:document-styles "
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'office:version="1.2">'
    "<office:styles/><office:automatic-styles/></office:document-styles>"
)

_META_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    "<office:document-meta "
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'office:version="1.2">'
    "<office:meta><meta:generator>repeated-cell-regression</meta:generator></office:meta>"
    "</office:document-meta>"
)

_MANIFEST_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    "<manifest:manifest "
    'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
    '<manifest:file-entry manifest:full-path="/" '
    'manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>'
    '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
    '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
    '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>'
    "</manifest:manifest>"
)


def _write_ods(tmp_path: Path, name: str, spreadsheet_inner: str) -> Path:
    out = tmp_path / name
    content_xml = _CONTENT_XML_TEMPLATE.format(spreadsheet_inner=spreadsheet_inner)
    with ZipFile(out, "w") as archive:
        archive.writestr("mimetype", _ODS_MIMETYPE, compress_type=ZIP_STORED)
        archive.writestr("content.xml", content_xml, compress_type=ZIP_DEFLATED)
        archive.writestr("styles.xml", _STYLES_XML, compress_type=ZIP_DEFLATED)
        archive.writestr("meta.xml", _META_XML, compress_type=ZIP_DEFLATED)
        archive.writestr("META-INF/manifest.xml", _MANIFEST_XML, compress_type=ZIP_DEFLATED)
    return out


def test_empty_repeated_columns_are_not_materialized(tmp_path: Path) -> None:
    spreadsheet_inner = (
        '<table:table table:name="Sheet1">'
        "<table:table-row>"
        "<table:table-cell><text:p>header</text:p></table:table-cell>"
        # LibreOffice "select all + format" filler — 16k empty styled columns.
        '<table:table-cell table:number-columns-repeated="16375"/>'
        "</table:table-row>"
        "<table:table-row>"
        "<table:table-cell><text:p>data</text:p></table:table-cell>"
        '<table:table-cell table:number-columns-repeated="16375"/>'
        "</table:table-row>"
        "</table:table>"
    )
    out = _write_ods(tmp_path, "empty_repeated_cols.ods", spreadsheet_inner)

    ir = parse_workbook(out)

    sheet = ir.sheets["Sheet1"]
    table = sheet.tables[0]
    assert table.n_cols == 1
    assert table.headers == ["header"]
    assert table.data == [["data"]]


def test_empty_repeated_rows_are_not_materialized(tmp_path: Path) -> None:
    spreadsheet_inner = (
        '<table:table table:name="Sheet1">'
        "<table:table-row>"
        "<table:table-cell><text:p>only_row</text:p></table:table-cell>"
        "</table:table-row>"
        # ~1M empty rows declared via row-repeated filler.
        '<table:table-row table:number-rows-repeated="1048534">'
        "<table:table-cell/>"
        "</table:table-row>"
        "</table:table>"
    )
    out = _write_ods(tmp_path, "empty_repeated_rows.ods", spreadsheet_inner)

    ir = parse_workbook(out)

    sheet = ir.sheets["Sheet1"]
    table = sheet.tables[0]
    assert table.n_cols == 1
    assert table.headers == ["only_row"]
    assert table.n_rows == 1


def test_non_empty_repeated_cells_are_still_materialized(tmp_path: Path) -> None:
    # Mirrors the real Dino pattern: a non-empty cell carrying col_repeat>1
    # represents repeated values across adjacent columns (pseudo-merge), not a
    # formatting filler — the parser must still write each position.
    spreadsheet_inner = (
        '<table:table table:name="Sheet1">'
        "<table:table-row>"
        '<table:table-cell office:value-type="string" table:number-columns-repeated="3">'
        "<text:p>Vorgeschichte</text:p>"
        "</table:table-cell>"
        '<table:table-cell table:number-columns-repeated="16375"/>'
        "</table:table-row>"
        "</table:table>"
    )
    out = _write_ods(tmp_path, "nonempty_repeated.ods", spreadsheet_inner)

    ir = parse_workbook(out)

    sheet = ir.sheets["Sheet1"]
    table = sheet.tables[0]
    assert table.n_cols == 3
    assert table.headers == ["Vorgeschichte", "Vorgeschichte", "Vorgeschichte"]


def test_parser_limits_reject_implausible_row_block(tmp_path: Path) -> None:
    # A row with real content declaring an implausible row-repeat must be
    # rejected before materialization. Using a low custom limit keeps the test
    # input small.
    spreadsheet_inner = (
        '<table:table table:name="Sheet1">'
        '<table:table-row table:number-rows-repeated="500">'
        "<table:table-cell><text:p>data</text:p></table:table-cell>"
        "</table:table-row>"
        "</table:table>"
    )
    out = _write_ods(tmp_path, "huge_row_block.ods", spreadsheet_inner)

    limits = ParserLimits(max_rows=100, max_cols=100, max_cells=100_000)
    with pytest.raises(SpreadsheetTooLargeError, match="row count 500"):
        parse_workbook(out, limits=limits)


def test_explicit_merge_span_extends_parsed_bounds() -> None:
    # Review follow-up: covered-table-cell siblings of a merged anchor must
    # not silently bound the parsed table. Before the bounds fix, an anchor
    # at col=1 with col_span=2 left max_col at 1, which dropped header merges
    # in _extract_header_merges and shrunk _find_col_extent's scan window.
    from odf.table import CoveredTableCell, Table, TableCell, TableRow
    from odf.text import P

    from spreadsheet_handling.io_backends.ods.parser_interpretation import (
        build_visible_sheet_ir,
    )

    table = Table(name="Sheet1")
    header = TableRow()
    anchor = TableCell(numbercolumnsspanned=2)
    anchor.addElement(P(text="Group"))
    header.addElement(anchor)
    header.addElement(CoveredTableCell())
    table.addElement(header)
    leaf = TableRow()
    left = TableCell()
    left.addElement(P(text="L"))
    right = TableCell()
    right.addElement(P(text="R"))
    leaf.addElement(left)
    leaf.addElement(right)
    table.addElement(leaf)

    parsed = _parse_table_grid(table)

    assert parsed.merges == [(1, 1, 1, 2)]
    assert parsed.max_col == 2
    assert parsed.max_row == 2

    sheet = build_visible_sheet_ir(
        parsed,
        sheet_name="Sheet1",
        meta_hints={},
        validations=[],
        autofilter_ref=None,
    )
    assert sheet.tables[0].n_cols == 2
    assert sheet.meta.get("__header_merges") == [(1, 1, 1, 2)]


_CONTENT_XML_TEMPLATE_WITH_STYLES = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    "<office:document-content "
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'office:version="1.2">'
    "<office:automatic-styles>{styles_inner}</office:automatic-styles>"
    "<office:body><office:spreadsheet>{spreadsheet_inner}</office:spreadsheet></office:body>"
    "</office:document-content>"
)


def _write_ods_with_styles(
    tmp_path: Path,
    name: str,
    styles_inner: str,
    spreadsheet_inner: str,
) -> Path:
    out = tmp_path / name
    content_xml = _CONTENT_XML_TEMPLATE_WITH_STYLES.format(
        styles_inner=styles_inner,
        spreadsheet_inner=spreadsheet_inner,
    )
    with ZipFile(out, "w") as archive:
        archive.writestr("mimetype", _ODS_MIMETYPE, compress_type=ZIP_STORED)
        archive.writestr("content.xml", content_xml, compress_type=ZIP_DEFLATED)
        archive.writestr("styles.xml", _STYLES_XML, compress_type=ZIP_DEFLATED)
        archive.writestr("meta.xml", _META_XML, compress_type=ZIP_DEFLATED)
        archive.writestr("META-INF/manifest.xml", _MANIFEST_XML, compress_type=ZIP_DEFLATED)
    return out


def test_display_metadata_extractors_clip_sheet_wide_rotated_filler(
    tmp_path: Path,
) -> None:
    # Regression for FTR-TEXT-ORIENTATION-ROUNDTRIP-P5: the LibreOffice
    # "select all + rotate" carrier pattern declares a single styled cell with
    # near-maximum number-rows-repeated x number-columns-repeated. Without
    # content-extent clipping, the text-orientation extractor would materialize
    # ~17e9 dict entries even though only one cell actually carries data.
    styles_inner = (
        '<style:style style:name="rot" style:family="table-cell">'
        '<style:table-cell-properties style:rotation-angle="90"/>'
        "</style:style>"
    )
    spreadsheet_inner = (
        '<table:table table:name="Sheet1">'
        "<table:table-row>"
        '<table:table-cell table:style-name="rot"><text:p>only</text:p></table:table-cell>'
        "</table:table-row>"
        # Whole-sheet styled filler block.
        '<table:table-row table:number-rows-repeated="1048575">'
        '<table:table-cell table:style-name="rot" table:number-columns-repeated="16384"/>'
        "</table:table-row>"
        "</table:table>"
    )
    out = _write_ods_with_styles(
        tmp_path, "rot_filler.ods", styles_inner, spreadsheet_inner
    )

    ir = parse_workbook(out)

    sheet = ir.sheets["Sheet1"]
    orients = sheet.meta.get("__text_orientations")
    # Only the real content cell may appear; filler rotations must be dropped
    # because they fall outside the parsed content extent.
    assert orients == {"A1": {"rotation": 90, "source": "workbook"}}


def test_display_metadata_extractors_reject_implausible_repeats(
    tmp_path: Path,
) -> None:
    # Defense-in-depth on the new extractor code paths: the grid parser does
    # not iterate table-column elements at all, so a column-width filler
    # declaring more columns than ParserLimits allows reaches limit
    # enforcement only via the column-width extractor. Without an explicit
    # enforce there, an implausible declaration would silently materialize.
    styles_inner = (
        '<style:style style:name="cw" style:family="table-column">'
        '<style:table-column-properties style:column-width="2.0cm"/>'
        "</style:style>"
    )
    spreadsheet_inner = (
        '<table:table table:name="Sheet1">'
        '<table:table-column table:style-name="cw" table:number-columns-repeated="200"/>'
        "<table:table-row>"
        "<table:table-cell><text:p>data</text:p></table:table-cell>"
        "</table:table-row>"
        "</table:table>"
    )
    out = _write_ods_with_styles(
        tmp_path, "cw_oversized.ods", styles_inner, spreadsheet_inner
    )

    limits = ParserLimits(max_rows=100, max_cols=100, max_cells=100_000)
    with pytest.raises(SpreadsheetTooLargeError, match="column count 200"):
        parse_workbook(out, limits=limits)


def test_column_width_extractor_clips_sheet_wide_filler(tmp_path: Path) -> None:
    # Mirror of the text-orientation guard for the column-width extractor:
    # a sheet-wide table-column with an explicit width style must not produce
    # 16k dict entries when actual content occupies only a handful of columns.
    styles_inner = (
        '<style:style style:name="cw" style:family="table-column">'
        '<style:table-column-properties style:column-width="2.0cm"/>'
        "</style:style>"
    )
    spreadsheet_inner = (
        '<table:table table:name="Sheet1">'
        '<table:table-column table:style-name="cw" table:number-columns-repeated="16384"/>'
        "<table:table-row>"
        "<table:table-cell><text:p>only</text:p></table:table-cell>"
        "</table:table-row>"
        "</table:table>"
    )
    out = _write_ods_with_styles(
        tmp_path, "cw_filler.ods", styles_inner, spreadsheet_inner
    )

    ir = parse_workbook(out)

    sheet = ir.sheets["Sheet1"]
    widths = sheet.meta.get("__column_widths") or {}
    assert set(widths.keys()) == {"A"}


def test_max_row_max_col_track_only_real_content() -> None:
    # Direct check on the parser's bounds: pathological filler cells around a
    # small island of real content must not inflate ParsedTable dimensions.
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    table = Table(name="Sheet1")

    row1 = TableRow()
    real_cell = TableCell()
    real_cell.addElement(P(text="real"))
    row1.addElement(real_cell)
    filler = TableCell()
    filler.setAttribute("numbercolumnsrepeated", "16375")
    row1.addElement(filler)
    table.addElement(row1)

    empty_block = TableRow()
    empty_block.setAttribute("numberrowsrepeated", "1048534")
    empty_block.addElement(TableCell())
    table.addElement(empty_block)

    parsed = _parse_table_grid(table)

    assert parsed.max_row == 1
    assert parsed.max_col == 1
    assert parsed.values == {(1, 1): "real"}
