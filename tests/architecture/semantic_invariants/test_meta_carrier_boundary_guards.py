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

from spreadsheet_handling.pipeline.persistence_boundary import (
    project_meta_to_persistable_contract,
)
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
    registry_path = repo_root / "registries" / "meta_registry.yaml"
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


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "backlog"
    / "fixtures"
    / "BUG-CROSS-CARRIER-META-ROUNDTRIP"
    / "ods_produced_meta.yaml"
)


def _load_ods_produced_meta_fixture() -> dict:
    with _FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.ftr("BUG-CROSS-CARRIER-META-ROUNDTRIP-P4A")
def test_persistence_boundary_prunes_resolution_facets_from_captured_fixture():
    """Architecture guard: the captured ODS-produced sidecar must lose its
    Intent-vs-Resolution Resolution facets when projected through the
    persistence boundary. See
    ``docs/backlog/BUG-CROSS-CARRIER-META-ROUNDTRIP.adoc`` and
    ``docs/warm_storage/reviews/assess_canonical_meta_boundary.adoc``
    (E2 narrow slice).
    """
    fixture = _load_ods_produced_meta_fixture()

    # Preconditions: the fixture must contain the Resolution facets so this
    # guard tests a real signal.
    assert "resolved" in fixture["legend_blocks"]["story_group_codes"], (
        "Fixture precondition failed: legend_blocks[*].resolved should be present"
    )
    any_xref_name, any_xref = next(iter(fixture["xref_crosstable"].items()))
    assert "column_keys" in any_xref, (
        f"Fixture precondition failed: xref_crosstable[{any_xref_name!r}].column_keys "
        "should be present"
    )
    assert "resolved" in any_xref["dense_axes"], (
        "Fixture precondition failed: xref_crosstable[*].dense_axes.resolved "
        "should be present"
    )

    projected = project_meta_to_persistable_contract(fixture)

    for name, block in projected["legend_blocks"].items():
        assert "resolved" not in block, (
            f"legend_blocks[{name!r}].resolved must be pruned at the "
            "persistence boundary"
        )
    for name, entry in projected["xref_crosstable"].items():
        assert "column_keys" not in entry, (
            f"xref_crosstable[{name!r}].column_keys must be pruned at the "
            "persistence boundary"
        )
        dense_axes = entry.get("dense_axes")
        if isinstance(dense_axes, dict):
            assert "resolved" not in dense_axes, (
                f"xref_crosstable[{name!r}].dense_axes.resolved must be pruned "
                "at the persistence boundary"
            )


@pytest.mark.ftr("BUG-CROSS-CARRIER-META-ROUNDTRIP-P4A")
def test_persistence_boundary_preserves_intent_in_captured_fixture():
    """Companion guard: Intent fields under the same canonical roots must
    survive the projection. The rule is "preserve Intent, drop Resolution",
    not "drop entire entries"."""
    fixture = _load_ods_produced_meta_fixture()
    projected = project_meta_to_persistable_contract(fixture)

    # Top-level Intent that must be untouched.
    assert projected["workbook_view"] == fixture["workbook_view"]
    assert projected["constraints"] == fixture["constraints"]
    assert projected["compact_multiaxis"] == fixture["compact_multiaxis"]

    # legend_blocks Intent.
    src_block = fixture["legend_blocks"]["story_group_codes"]
    out_block = projected["legend_blocks"]["story_group_codes"]
    assert out_block["title"] == src_block["title"]
    assert out_block["entries"] == src_block["entries"]
    assert out_block["placement"] == src_block["placement"]

    # xref_crosstable Intent.
    for name, src in fixture["xref_crosstable"].items():
        out_entry = projected["xref_crosstable"][name]
        for intent_key in ("column_key", "row_keys", "relation", "operation"):
            if intent_key in src:
                assert out_entry[intent_key] == src[intent_key], (
                    f"xref_crosstable[{name!r}].{intent_key} must survive the "
                    "persistence boundary"
                )
        src_dense = src.get("dense_axes")
        if isinstance(src_dense, dict):
            out_dense = out_entry["dense_axes"]
            assert out_dense["columns_from"] == src_dense["columns_from"]
            assert out_dense["rows_from"] == src_dense["rows_from"]


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
