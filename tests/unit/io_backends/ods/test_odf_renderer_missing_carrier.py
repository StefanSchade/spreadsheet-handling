"""ODS renderer carrier-missing regression for BUG-ODS-MISSING-CARRIER-LITERAL-NAN-RENDERING-P4A.

The per-cell write branch used to test emptiness with ``value in (None, "")``.
Python's ``in`` uses ``==``, and ``float('nan') == float('nan')`` is ``False``
(IEEE-754), so a real pandas/NumPy missing carrier fell through into the
numeric branch and was serialized as the literal paragraph text ``"nan"``.

This is a renderer/carrier-level unit test: it constructs a render-IR
``WriteDataBlock`` directly (independent of the roundtrip layer) so the fix
is pinned at the boundary that owns it, per this BUG's "Required future
regression evidence" section.
"""

from __future__ import annotations

import math
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from spreadsheet_handling.io_backends.ods.odf_renderer import render_workbook
from spreadsheet_handling.rendering.plan import DefineSheet, RenderPlan, SetHeader, WriteDataBlock


pytestmark = pytest.mark.ftr("BUG-ODS-MISSING-CARRIER-LITERAL-NAN-RENDERING-P4A")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(elem: ET.Element, local_name: str) -> str | None:
    for key, value in elem.attrib.items():
        if _local_name(key) == local_name:
            return value
    return None


def _cell_text(cell: ET.Element) -> str:
    return "".join(p.text or "" for p in cell.iter() if _local_name(p.tag) == "p")


# Case name -> (in-memory value, expected office:value-type, expected paragraph text).
# ``None`` for the expected value-type means the cell must render blank (no
# office:value-type attribute at all), matching the existing None/"" branch.
_CASES: list[tuple[str, object, str | None, str]] = [
    ("python_none", None, None, ""),
    ("math_nan", math.nan, None, ""),
    ("numpy_float64_nan", np.float64("nan"), None, ""),
    ("pandas_na", pd.NA, None, ""),
    ("legitimate_empty_string", "", None, ""),
    ("literal_domain_string_nan", "nan", "string", "nan"),
    ("integer", 42, "float", "42"),
    ("float_value", 3.14, "float", "3.14"),
    ("bool_true", True, "boolean", "TRUE"),
    ("bool_false", False, "boolean", "FALSE"),
]


def _render_cases(tmp_path: Path) -> list[ET.Element]:
    plan = RenderPlan()
    plan.add(DefineSheet("Sheet1", 1))
    for idx, (name, _value, _vtype, _text) in enumerate(_CASES, start=1):
        plan.add(SetHeader("Sheet1", 1, idx, name))
    row = tuple(value for _, value, _vtype, _text in _CASES)
    plan.add(WriteDataBlock("Sheet1", 2, 1, (row,)))

    out = tmp_path / "missing_carrier.ods"
    render_workbook(plan, out)
    out = out.with_suffix(".ods")

    with ZipFile(out) as archive:
        root = ET.fromstring(archive.read("content.xml"))

    cells = [e for e in root.iter() if _local_name(e.tag) == "table-cell"]
    # First len(_CASES) cells are the header row; the next len(_CASES) are
    # the data row under test.
    return cells[len(_CASES) : 2 * len(_CASES)]


def test_missing_carrier_and_pathological_values_render_as_expected(tmp_path: Path) -> None:
    data_cells = _render_cases(tmp_path)
    assert len(data_cells) == len(_CASES)

    for (name, value, expected_vtype, expected_text), cell in zip(_CASES, data_cells):
        vtype = _attr(cell, "value-type")
        text = _cell_text(cell)
        assert vtype == expected_vtype, (
            f"case {name!r} (value={value!r}): expected office:value-type="
            f"{expected_vtype!r}, got {vtype!r}"
        )
        assert text == expected_text, (
            f"case {name!r} (value={value!r}): expected paragraph text="
            f"{expected_text!r}, got {text!r}"
        )
        # The specific corruption this BUG pins: a missing carrier must never
        # surface as the literal text "nan".
        if name != "literal_domain_string_nan":
            assert text != "nan", (
                f"case {name!r} (value={value!r}) must not serialize as the "
                f"literal string 'nan'"
            )
