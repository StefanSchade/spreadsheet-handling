"""Focused unit tests for the ODS cell-style cache.

The ``_register_cell_style`` cache key was extended from a 4-tuple to a
5-tuple by ``FTR-VERTICAL-ALIGNMENT-ROUNDTRIP-P5`` to accommodate
``vertical_alignment``. The acceptance criterion this file pins is that
two styles differing only in vertical alignment receive distinct style
names — i.e. no false cache hit caused by an under-keyed sentinel or a
forgotten field in ``_style_key``.
"""

from __future__ import annotations

import pytest

from odf.opendocument import OpenDocumentSpreadsheet

from spreadsheet_handling.io_backends.ods.odf_renderer import (
    CellStyleKey,
    _register_cell_style,
)


pytestmark = pytest.mark.ftr("FTR-VERTICAL-ALIGNMENT-ROUNDTRIP-P5")


def test_styles_differing_only_in_vertical_alignment_get_distinct_names():
    doc = OpenDocumentSpreadsheet()
    cache: dict[CellStyleKey, str] = {}

    name_top = _register_cell_style(
        doc, cache, bold=False, fill_rgb=None, vertical_alignment="top"
    )
    name_center = _register_cell_style(
        doc, cache, bold=False, fill_rgb=None, vertical_alignment="center"
    )
    name_bottom = _register_cell_style(
        doc, cache, bold=False, fill_rgb=None, vertical_alignment="bottom"
    )

    assert name_top is not None
    assert name_center is not None
    assert name_bottom is not None
    assert len({name_top, name_center, name_bottom}) == 3, (
        "Two styles differing only in vertical alignment must receive "
        "distinct style names; got "
        f"{name_top!r}, {name_center!r}, {name_bottom!r}."
    )


def test_styles_differing_only_in_horizontal_and_vertical_get_distinct_names():
    # Regression guard for the 5-tuple cache key: combinations of
    # horizontal and vertical alignment should produce distinct styles
    # rather than colliding because one of the two fields is ignored by
    # ``_style_key``.
    doc = OpenDocumentSpreadsheet()
    cache: dict[CellStyleKey, str] = {}

    a = _register_cell_style(
        doc,
        cache,
        bold=False,
        fill_rgb=None,
        horizontal_alignment="left",
        vertical_alignment="top",
    )
    b = _register_cell_style(
        doc,
        cache,
        bold=False,
        fill_rgb=None,
        horizontal_alignment="left",
        vertical_alignment="bottom",
    )
    c = _register_cell_style(
        doc,
        cache,
        bold=False,
        fill_rgb=None,
        horizontal_alignment="right",
        vertical_alignment="top",
    )

    assert len({a, b, c}) == 3


def test_default_only_style_returns_none():
    # The early-exit sentinel is now ``(False, None, 0, None, None)``; a
    # call with all defaults must yield ``None`` so that the renderer
    # emits no ``stylename`` attribute on the cell.
    doc = OpenDocumentSpreadsheet()
    cache: dict[CellStyleKey, str] = {}

    assert _register_cell_style(doc, cache, bold=False, fill_rgb=None) is None
    assert cache == {}
