"""Meta/carrier boundary guards for spreadsheet metadata.

These checks keep canonical workbook metadata distinct from IR-local rendering
views and backend carrier artifacts. They intentionally guard the current seam
without introducing a new metadata model.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from spreadsheet_handling.rendering.ir import SheetIR, WorkbookIR
from spreadsheet_handling.rendering.workbook_projection import workbookir_to_frames


pytestmark = pytest.mark.ftr("FTR-META-CARRIER-BOUNDARY-GUARDS-P4")


CARRIER_OR_RENDERING_META_KEYS = {
    "workbook_meta_blob",
    "options",
    "__style",
    "__helper_cols",
    "__autofilter",
    "__freeze",
    "__autofilter_ref",
    "_hidden",
}


def _load_registry() -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    registry_path = repo_root / "docs" / "internal_guide" / "architecture" / "meta_registry.yaml"
    with registry_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return loaded


def _registry_entries_by_name() -> dict[str, dict]:
    registry = _load_registry()
    return {entry["name"]: entry for entry in registry["entries"]}


def test_carrier_or_rendering_registry_entries_are_not_canonical_meta():
    entries = _registry_entries_by_name()

    for key in CARRIER_OR_RENDERING_META_KEYS:
        entry = entries[key]
        assert entry["layer"] == "meta_rendering"
        assert entry["classification"] != "canonical_meta"


def test_canonical_registry_entries_do_not_use_carrier_shaped_names():
    entries = _registry_entries_by_name()

    for entry in entries.values():
        if entry["classification"] != "canonical_meta":
            continue

        assert entry["layer"] == "meta_canonical"
        assert entry["name"] not in CARRIER_OR_RENDERING_META_KEYS
        assert not entry["name"].startswith("_")


def test_workbook_projection_prefers_canonical_payload_over_carrier_hints():
    canonical_meta = {
        "version": "4.0",
        "author": "meta-carrier-boundary",
        "freeze_header": True,
        "auto_filter": True,
    }
    ir = WorkbookIR(
        sheets={
            "Products": SheetIR(
                name="Products",
                meta={
                    "options": {"freeze_header": False},
                    "__freeze": {"row": 3, "col": 1},
                    "__autofilter_ref": "A1:B3",
                },
            )
        },
        hidden_sheets={
            "_meta": SheetIR(
                name="_meta",
                meta={
                    "_hidden": True,
                    "workbook_meta_blob": json.dumps(canonical_meta),
                    "__freeze": {"row": 99, "col": 99},
                    "options": {"auto_filter": False},
                },
            )
        },
    )

    frames = workbookir_to_frames(ir)

    assert frames["_meta"] == canonical_meta
    assert "__freeze" not in frames["_meta"]
    assert "__autofilter_ref" not in frames["_meta"]
    assert "options" not in frames["_meta"]
