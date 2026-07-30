"""Semantic invariants for the architecture meta registry artifact.

These checks keep the registry structurally well-formed and preserve the
reviewed maintenance contract that separates canonical and rendering-side meta.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.ftr("FTR-META-REGISTRY-P3H"),
    pytest.mark.ftr("FTR-META-REGISTRY-HARDENING-P3I"),
    pytest.mark.ftr("FTR-REVIEW-001-META-REGISTRY-DERIVED-P3"),
]


def _load_registry() -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    registry_path = repo_root / "registries" / "meta_registry.yaml"
    with registry_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return loaded


def test_meta_registry_has_required_profile_fields():
    registry = _load_registry()
    entries = registry.get("entries")
    maintenance_contract = registry.get("maintenance_contract")

    assert registry.get("registry_version") == 2
    assert isinstance(entries, list)
    assert entries
    assert isinstance(maintenance_contract, dict)

    required_fields = set(maintenance_contract.get("common_required_fields", []))

    for entry in entries:
        assert required_fields <= set(entry)
        assert isinstance(entry["producer"], list)
        assert entry["producer"]
        assert isinstance(entry["consumer"], list)
        assert entry["consumer"]


def test_meta_registry_entry_names_are_unique():
    registry = _load_registry()
    names = [entry["name"] for entry in registry["entries"]]

    assert len(names) == len(set(names))


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
def test_legend_blocks_entry_names_reviewed_producers_and_consumers():
    """Guard the reviewed legend_blocks producer/consumer surface (LB-7).

    The registry must name domain.ingress as the canonical-shape producer, the
    composer as the carrier-local resolved producer, and every current semantic
    reader/projector as a consumer. This is a focused list guard, not a generic
    source-scanning framework.
    """
    registry = _load_registry()
    entry = next(e for e in registry["entries"] if e["name"] == "legend_blocks")

    producers = set(entry["producer"])
    consumers = set(entry["consumer"])

    assert {
        "domain.ingress.run_domain_ingress",
        "rendering.composer.layout_composer.compose_workbook",
    } <= producers

    assert {
        "domain.transformations._legend_blocks._read_legend_block",
        "domain.transformations.cell_codec.scalar",
        "domain.transformations.compact_multiaxis",
        "rendering.passes.validation_pass.ValidationPass",
        "rendering.composer.layout_composer.compose_workbook",
        "io_backends.xlsx.openpyxl_parser.parse_workbook",
        "io_backends.ods.odf_parser.parse_workbook",
        "domain.schema_maintenance.meta_update",
        "pipeline.persistence_boundary.project_meta_to_persistable_contract",
        "rendering.workbook_projection.workbookir_to_frames",
    } <= consumers

    # Canonical mapping-only shape and the ingress normalization are documented.
    scope_and_origin = f"{entry['scope']} {entry['origin']}".lower()
    assert "mapping" in scope_and_origin
    assert "ingress" in scope_and_origin


def test_meta_registry_seeds_current_known_entries():
    registry = _load_registry()
    names = {entry["name"] for entry in registry["entries"]}

    assert {
        "version",
        "author",
        "exported_at",
        "constraints",
        "legend_blocks",
        "xref_crosstable",
        "compact_multiaxis",
        "sparse_defaults",
        "freeze_header",
        "auto_filter",
        "column_widths",
        "header_fill_rgb",
        "helper_fill_rgb",
        "helper_prefix",
        "helper_columns",
        "workbook_view",
        "workbook_view.sheet_mappings",
        "sheets",
        "workbook_meta_blob",
        "options",
        "__style",
        "__helper_cols",
        "__autofilter",
        "__freeze",
        "__autofilter_ref",
        "_hidden",
        "derived",
        "pipeline_cleanup",
    } <= names


def test_meta_registry_registers_derived_channel_contract():
    registry = _load_registry()
    entries = {entry["name"]: entry for entry in registry["entries"]}

    derived = entries["derived"]

    assert derived["layer"] == "meta_rendering"
    assert derived["classification"] == "derived_operational_view"
    assert derived["lifecycle"] == "transient"
    assert derived["producer"]
    assert derived["consumer"]
    assert "domain.transformations.enrich_lookup.operation._write_provenance" in derived["producer"]
    assert "domain.transformations.fk_helpers._write_helper_provenance" in derived["producer"]
    assert "rendering.passes._base._derived_helper_column_names" in derived["consumer"]
    assert "domain.transformations.fk_helpers.drop_helpers" in derived["consumer"]


def test_meta_registry_exposes_maintenance_contract():
    registry = _load_registry()
    maintenance_contract = registry.get("maintenance_contract")
    reference_conventions = registry.get("reference_conventions")

    assert isinstance(maintenance_contract, dict)
    assert maintenance_contract.get("maintenance_mode") == "manual_review_artifact"
    assert maintenance_contract.get("runtime_binding") == "forbidden"
    assert {
        "canonical_meta",
        "derived_operational_view",
        "carrier_artifact",
        "read_path_hint",
    } <= set(maintenance_contract.get("allowed_classifications", []))
    assert {
        "meta_canonical",
        "meta_rendering",
    } <= set(maintenance_contract.get("allowed_layers", []))

    assert isinstance(reference_conventions, dict)
    assert reference_conventions.get("code_reference_prefix") == "spreadsheet_handling"
    assert isinstance(reference_conventions.get("approved_narrative_references"), list)
