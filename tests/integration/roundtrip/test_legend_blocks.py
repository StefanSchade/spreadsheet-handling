"""Legend-block roundtrip integration slice.

Guards that rendered legend blocks survive XLSX and ODS roundtrips as metadata
rather than becoming ordinary data frames.
"""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.ods.odf_parser import parse_workbook as parse_ods_workbook
from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.io_backends.xlsx.openpyxl_parser import parse_workbook
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from spreadsheet_handling.pipeline.persistence_boundary import (
    project_meta_to_persistable_contract,
)

pytestmark = [
    pytest.mark.ftr("FTR-LEGEND-BLOCKS"),
    pytest.mark.ftr("FTR-TEST-NAMING-AND-CONVENTIONS-P3C"),
]


def _frames_with_legend() -> dict:
    meta = {
        "legend_blocks": {
            "status_codes": {
                "title": "Status Codes",
                "placement": {
                    "sheet": "product_matrix",
                    "anchor": "right_of_table",
                    "target": "product_matrix",
                },
                "entries": [
                    {"token": "E", "label": "Editable", "group": "input"},
                    {"token": "E-R-K", "label": "Capital-path recalculation", "group": "input"},
                    {"token": "x", "label": "Not meaningful", "group": "blocked"},
                ],
            }
        }
    }
    return {
        "product_matrix": pd.DataFrame(
            {
                "feature": ["currency", "amount"],
                "FZ-AD": ["E", "E-R-K"],
            }
        ),
        "_meta": meta,
    }


def test_xlsx_legend_block_roundtrips_as_metadata_not_data_frame(tmp_path):
    frames = _frames_with_legend()
    meta_before = copy.deepcopy(frames["_meta"])
    xlsx = tmp_path / "legend.xlsx"
    ExcelBackend().write_multi(frames, str(xlsx))

    ir = parse_workbook(xlsx)
    sheet = ir.sheets["product_matrix"]

    assert len(sheet.tables) == 2
    assert sheet.tables[0].kind == "data"
    assert sheet.tables[0].headers == ["feature", "FZ-AD"]
    assert sheet.tables[1].kind == "legend"
    assert sheet.tables[1].headers == ["Token", "Meaning", "Group"]
    assert sheet.tables[1].data[1] == ["E-R-K", "Capital-path recalculation", "input"]

    back = ExcelBackend().read_multi(str(xlsx), header_levels=1)
    assert list(back["product_matrix"].columns) == ["feature", "FZ-AD"]
    assert back["product_matrix"].to_dict(orient="records") == [
        {"feature": "currency", "FZ-AD": "E"},
        {"feature": "amount", "FZ-AD": "E-R-K"},
    ]
    assert "legend_blocks" in back["_meta"]
    assert frames["_meta"] == meta_before


def test_ods_legend_block_roundtrips_as_metadata_not_data_frame(tmp_path):
    ods = tmp_path / "legend.ods"
    OdsBackend().write_multi(_frames_with_legend(), str(ods))

    ir = parse_ods_workbook(ods)
    sheet = ir.sheets["product_matrix"]

    assert len(sheet.tables) == 2
    assert sheet.tables[0].kind == "data"
    assert sheet.tables[0].headers == ["feature", "FZ-AD"]
    assert sheet.tables[1].kind == "legend"
    assert sheet.tables[1].headers == ["Token", "Meaning", "Group"]
    assert sheet.tables[1].data[1] == ["E-R-K", "Capital-path recalculation", "input"]

    back = OdsBackend().read_multi(str(ods), header_levels=1)
    assert list(back["product_matrix"].columns) == ["feature", "FZ-AD"]
    assert back["product_matrix"].to_dict(orient="records") == [
        {"feature": "currency", "FZ-AD": "E"},
        {"feature": "amount", "FZ-AD": "E-R-K"},
    ]
    assert "legend_blocks" in back["_meta"]


# ---------------------------------------------------------------------------
# FTR-LEGEND-BLOCKS-LIFECYCLE-P6 -- Slice B characterization
# ---------------------------------------------------------------------------


def _find_key(node, key) -> bool:
    """True if ``key`` appears anywhere in a nested dict/list structure."""
    if isinstance(node, dict):
        if key in node:
            return True
        return any(_find_key(v, key) for v in node.values())
    if isinstance(node, list):
        return any(_find_key(v, key) for v in node)
    return False


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-LIFECYCLE-P6")
def test_resolved_and_dunder_hint_do_not_reach_sidecar(tmp_path):
    """The workbook-embedded carrier keeps ``resolved``; the structured sidecar
    projection drops it and never carries ``__legend_blocks``."""
    xlsx = tmp_path / "legend.xlsx"
    ExcelBackend().write_multi(_frames_with_legend(), str(xlsx))

    back = ExcelBackend().read_multi(str(xlsx), header_levels=1)
    back_meta = back["_meta"]

    # Carrier readback characterization: resolved is present (workbook carrier),
    # and the read-path-only __legend_blocks hint does not propagate to meta.
    assert _find_key(back_meta["legend_blocks"], "resolved")
    assert not _find_key(back_meta, "__legend_blocks")

    # Structured sidecar projection: resolved stripped, no dunder hint, intent kept.
    sidecar = project_meta_to_persistable_contract(back_meta)
    block = sidecar["legend_blocks"]["status_codes"]
    assert not _find_key(sidecar["legend_blocks"], "resolved")
    assert not _find_key(sidecar, "__legend_blocks")
    assert block["title"] == "Status Codes"
    assert block["placement"]["target"] == "product_matrix"
    assert [e["token"] for e in block["entries"]] == ["E", "E-R-K", "x"]


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-LIFECYCLE-P6")
def test_legend_classification_is_load_bearing_not_dunder_hint(tmp_path):
    """``table.kind == "legend"`` is the load-bearing artifact. The
    ``__legend_blocks`` sheet-meta hint was removed in Slice C; classification
    and frame projection do not depend on it.
    """
    xlsx = tmp_path / "legend.xlsx"
    ExcelBackend().write_multi(_frames_with_legend(), str(xlsx))

    ir = parse_workbook(xlsx)
    sheet = ir.sheets["product_matrix"]

    # Load-bearing: the legend table is classified, not emitted as data.
    kinds = [t.kind for t in sheet.tables]
    assert kinds == ["data", "legend"]

    # The __legend_blocks hint is no longer produced (Slice C). Classification
    # via table.kind is unaffected by its removal.
    assert "__legend_blocks" not in sheet.meta

    # The rendered legend does not become a payload frame; the removed hint does not
    # reach the returned/persistable meta.
    back = ExcelBackend().read_multi(str(xlsx), header_levels=1)
    assert set(back) == {"_meta", "product_matrix"}
    assert not _find_key(back["_meta"], "__legend_blocks")


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-LIFECYCLE-P6")
def test_second_roundtrip_rebuilds_legend_from_config_source(tmp_path):
    """Forward -> reverse -> forward again rebuilds the legend (entries and a
    freshly computed ``resolved``) from the config-backed source, with no
    dependency on a prior sidecar ``resolved``."""
    # First forward + reverse, then project to the structured sidecar form.
    xlsx1 = tmp_path / "legend1.xlsx"
    ExcelBackend().write_multi(_frames_with_legend(), str(xlsx1))
    back1 = ExcelBackend().read_multi(str(xlsx1), header_levels=1)
    sidecar1 = project_meta_to_persistable_contract(back1["_meta"])

    # Precondition: the second forward run's input has NO resolved facet.
    assert not _find_key(sidecar1["legend_blocks"], "resolved")
    assert [e["token"] for e in sidecar1["legend_blocks"]["status_codes"]["entries"]] == [
        "E",
        "E-R-K",
        "x",
    ]

    # Second forward run from the config-backed sidecar meta.
    frames2 = {"product_matrix": back1["product_matrix"], "_meta": sidecar1}
    xlsx2 = tmp_path / "legend2.xlsx"
    ExcelBackend().write_multi(frames2, str(xlsx2))

    ir2 = parse_workbook(xlsx2)
    sheet2 = ir2.sheets["product_matrix"]
    assert [t.kind for t in sheet2.tables] == ["data", "legend"]
    # Legend table rebuilt from entries.
    assert sheet2.tables[1].headers == ["Token", "Meaning", "Group"]
    assert sheet2.tables[1].data[1] == ["E-R-K", "Capital-path recalculation", "input"]

    # resolved is re-derived on the second pass, even though the input had none.
    back2 = ExcelBackend().read_multi(str(xlsx2), header_levels=1)
    assert _find_key(back2["_meta"]["legend_blocks"], "resolved")
