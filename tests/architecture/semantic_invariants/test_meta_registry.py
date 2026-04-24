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
]


def _load_registry() -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    registry_path = repo_root / "docs" / "internal_guide" / "architecture" / "meta_registry.yaml"
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


def test_meta_registry_seeds_current_known_entries():
    registry = _load_registry()
    names = {entry["name"] for entry in registry["entries"]}

    assert {
        "version",
        "author",
        "exported_at",
        "constraints",
        "freeze_header",
        "auto_filter",
        "header_fill_rgb",
        "helper_fill_rgb",
        "helper_prefix",
        "sheets",
        "workbook_meta_blob",
        "options",
        "__style",
        "__helper_cols",
        "__autofilter",
        "__freeze",
        "__autofilter_ref",
        "_hidden",
    } <= names


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
